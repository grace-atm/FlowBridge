"""Public GitHub archive acquisition with controlled redirects and a total deadline."""

import asyncio
import json
import re
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit

import httpx

from .config import GitHubSettings, ImportLimits, MiB
from .errors import (
    GitHubRateLimited,
    GitHubTimeout,
    GitHubUnavailable,
    ImportLimitExceeded,
    InvalidGitHubRedirect,
    InvalidGitHubURL,
    NoPythonFiles,
)

_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def parse_repository_url(url: str) -> tuple[str, str]:
    """Accept only HTTPS github.com repository roots, optionally ending in .git."""
    message = "Use a repository root URL: https://github.com/owner/repository (no tree/blob path)."
    try:
        if not url or any(ord(char) < 33 or ord(char) == 127 for char in url):
            raise ValueError
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "github.com"
            or "?" in url
            or "#" in url
        ):
            raise ValueError
        path = parsed.path.removesuffix("/")
        parts = path.split("/")
        if len(parts) != 3 or parts[0]:
            raise ValueError
        owner, repository = parts[1], parts[2].removesuffix(".git")
        if (
            not _OWNER.fullmatch(owner)
            or not _REPOSITORY.fullmatch(repository)
            or repository in {".", ".."}
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise InvalidGitHubURL(message) from None
    return owner, repository


@dataclass(frozen=True)
class RepositoryArchive:
    name: str
    data: bytes
    wrapper_prefix: str


class GitHubDownloader:
    """One import per instance; injected clients are owned/closed by the caller.

    Network work is asynchronous internally so asyncio.timeout can cancel a slow
    streaming response at the overall deadline, including a continuously busy one.
    CodeManager's synchronous adapter runs this coroutine in its worker thread.
    """

    def __init__(
        self,
        limits: ImportLimits,
        settings: GitHubSettings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.limits = limits
        self.settings = settings
        self.client = client
        self._redirects = 0

    async def fetch(self, url: str) -> RepositoryArchive:
        owner, repository = parse_repository_url(url)
        try:
            async with asyncio.timeout(self.settings.overall_timeout):
                if self.client is not None:
                    return await self._fetch(self.client, owner, repository)
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                    return await self._fetch(client, owner, repository)
        except (TimeoutError, httpx.TimeoutException):
            raise GitHubTimeout("GitHub import timed out. Try again later.") from None
        except httpx.HTTPError:
            raise GitHubUnavailable(
                "GitHub could not be reached or returned an invalid response."
            ) from None

    async def _fetch(
        self, client: httpx.AsyncClient, owner: str, repository: str
    ) -> RepositoryArchive:
        base = f"https://api.github.com/repos/{owner}/{repository}"
        raw = await self._get(client, base, MiB, metadata=True)
        try:
            metadata = json.loads(raw)
        except (ValueError, UnicodeError):
            raise GitHubUnavailable("GitHub returned invalid repository metadata.") from None
        if not isinstance(metadata, dict) or metadata.get("private") is not False:
            raise GitHubUnavailable("Only accessible public repositories can be imported.")
        if metadata.get("visibility", "public") != "public":
            raise GitHubUnavailable("Only accessible public repositories can be imported.")
        branch = metadata.get("default_branch")
        if branch is None or branch == "":
            raise NoPythonFiles("The GitHub repository is empty.")
        if not isinstance(branch, str):
            raise GitHubUnavailable("GitHub returned invalid default-branch metadata.")

        # A repository may have been renamed. Use validated canonical metadata
        # only for the known archive wrapper; never follow metadata-provided URLs.
        canonical_owner = metadata.get("owner", {})
        if not isinstance(canonical_owner, dict):
            raise GitHubUnavailable("GitHub returned invalid repository metadata.")
        canonical_owner = canonical_owner.get("login", owner)
        canonical_name = metadata.get("name", repository)
        if (
            not isinstance(canonical_owner, str)
            or not _OWNER.fullmatch(canonical_owner)
            or not isinstance(canonical_name, str)
            or not _REPOSITORY.fullmatch(canonical_name)
            or canonical_name in {".", ".."}
        ):
            raise GitHubUnavailable("GitHub returned invalid repository metadata.")
        archive = await self._get(
            client,
            f"{base}/zipball/{quote(branch, safe='')}",
            self.limits.max_archive_bytes,
            metadata=False,
        )
        return RepositoryArchive(canonical_name, archive, f"{canonical_owner}-{canonical_name}-")

    async def _get(
        self, client: httpx.AsyncClient, url: str, limit: int, *, metadata: bool
    ) -> bytes:
        while True:
            self._validate_destination(url, metadata=metadata)
            headers = {
                "Accept": "application/vnd.github+json" if metadata else "application/zip",
                "Accept-Encoding": "identity",
                "User-Agent": "FlowBridge-CodeManager/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if urlsplit(url).hostname == "api.github.com" and self.settings.token:
                headers["Authorization"] = f"Bearer {self.settings.token}"
            timeout = httpx.Timeout(
                self.settings.read_timeout, connect=self.settings.connect_timeout
            )
            # Construct a fresh Request instead of inheriting client headers,
            # cookies, query parameters, or credentials across archive redirects.
            request = httpx.Request(
                "GET", url, headers=headers, extensions={"timeout": timeout.as_dict()}
            )
            response = await client.send(request, stream=True, follow_redirects=False, auth=None)
            try:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location or self._redirects >= self.settings.max_redirects:
                        raise InvalidGitHubRedirect(
                            "GitHub archive redirect is missing or exceeds the limit."
                        )
                    self._redirects += 1
                    try:
                        url = urljoin(url, location)
                    except ValueError:
                        raise InvalidGitHubRedirect(
                            "GitHub returned a malformed redirect."
                        ) from None
                    # Validate before making the next request.
                    self._validate_destination(url, metadata=metadata)
                    continue
                self._check_status(response, metadata=metadata)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise GitHubUnavailable("GitHub returned an unsupported content encoding.")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        length = int(declared)
                        if length < 0:
                            raise ValueError
                    except ValueError:
                        raise GitHubUnavailable(
                            "GitHub returned an invalid content length."
                        ) from None
                    if length > limit:
                        raise ImportLimitExceeded(
                            "GitHub response exceeds the configured byte limit."
                        )
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=min(64 * 1024, limit + 1)):
                    if len(data) + len(chunk) > limit:
                        raise ImportLimitExceeded(
                            "GitHub response exceeds the configured byte limit."
                        )
                    data.extend(chunk)
                return bytes(data)
            finally:
                await response.aclose()

    @staticmethod
    def _validate_destination(url: str, *, metadata: bool) -> None:
        try:
            parsed = urlsplit(url)
            hosts = {"api.github.com"} if metadata else {"api.github.com", "codeload.github.com"}
            if (
                parsed.scheme != "https"
                or parsed.hostname not in hosts
                or parsed.netloc.lower() != parsed.hostname
                or parsed.fragment
                or any(ord(char) < 33 or ord(char) == 127 for char in url)
            ):
                raise ValueError
        except ValueError:
            raise InvalidGitHubRedirect(
                "GitHub redirected to an unsupported destination."
            ) from None

    @staticmethod
    def _check_status(response: httpx.Response, *, metadata: bool) -> None:
        status = response.status_code
        if status == 429 or (
            status == 403
            and (
                response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
            )
        ):
            raise GitHubRateLimited(
                "GitHub rate limit reached. Try again later or configure GITHUB_TOKEN."
            )
        if status == 404 and not metadata:
            raise NoPythonFiles("GitHub repository is empty or its default branch is unavailable.")
        if status in {401, 403, 404}:
            raise GitHubUnavailable("GitHub repository is missing, private, or inaccessible.")
        if status != 200:
            raise GitHubUnavailable("GitHub returned an unsuccessful response.")
