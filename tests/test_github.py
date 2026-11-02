import asyncio
import io
from dataclasses import replace

import httpx
import pytest

from flowbridge import CodeManager
from flowbridge.config import GitHubSettings, ImportLimits
from flowbridge.errors import (
    GitHubRateLimited,
    GitHubTimeout,
    GitHubUnavailable,
    ImportLimitExceeded,
    InvalidArchive,
    InvalidGitHubRedirect,
    InvalidGitHubURL,
    InvalidInput,
    InvalidSourceEncoding,
    NoPythonFiles,
)

ROOT = "https://github.com/student/demo"
API = "https://api.github.com/repos/student/demo"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data: bytes, *, delay: float = 0):
        self.data = data
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for index in range(0, len(self.data), 2):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield self.data[index : index + 2]

    async def aclose(self):
        self.closed = True


def test_metadata_default_branch_redirect_source_and_credentials(make_zip, mock_client):
    requests = []
    content = b"if True:\r\n\tpass\r\n"
    data = make_zip(
        [
            ("student-demo-abc1234/", b""),
            ("student-demo-abc1234/tests/main.py", b"# tests\n"),
            ("student-demo-abc1234/app/main.py", content),
            ("student-demo-abc1234/venv/bad.py", b"\xff"),
        ]
    )

    def handler(request):
        requests.append(request)
        if str(request.url) == API:
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(
                200,
                json={
                    "private": False,
                    "default_branch": "release/demo",
                    "name": "demo",
                    "owner": {"login": "student"},
                },
            )
        if request.url.host == "api.github.com":
            assert request.url.raw_path == b"/repos/student/demo/zipball/release%2Fdemo"
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(
                302,
                headers={
                    "location": "https://codeload.github.com/student/demo/legacy.zip/release/demo"
                },
            )
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert not request.url.params
        return httpx.Response(200, stream=Chunks(data))

    client = mock_client(
        handler,
        headers={"Authorization": "must-not-inherit", "Cookie": "secret=1"},
        params={"token": "must-not-inherit"},
        auth=("user", "password"),
    )
    manager = CodeManager(github_client=client, github_settings=GitHubSettings(token="test-token"))
    files = manager.loadGit(ROOT)
    assert isinstance(files, list) and len(files) == 2
    assert [f.filePath for f in files] == ["app/main.py", "tests/main.py"]
    assert files[0].fileContent == content.decode()
    assert files[0].fileID != files[1].fileID
    assert manager.getProject().projectName == "demo"
    assert len(requests) == 3
    assert all(request.extensions["timeout"]["connect"] == 5 for request in requests)
    assert not client.is_closed


@pytest.mark.parametrize("suffix", ["", "/", ".git", ".git/"])
def test_valid_repository_root_forms(suffix, make_zip, mock_client):
    data = make_zip([("student-demo-abc1234/main.py", b"")])
    client = mock_client(
        lambda req: (
            httpx.Response(200, json={"private": False, "default_branch": "develop"})
            if str(req.url) == API
            else httpx.Response(200, content=data)
        )
    )
    manager = CodeManager(github_client=client)
    manager.loadGit(ROOT + suffix, projectName=" My Git Project ")
    assert manager.getProject().projectName == "My Git Project"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/student/demo",
        "https://example.com/student/demo",
        "https://github.com.evil.test/student/demo",
        "git@github.com:student/demo.git",
        "ssh://github.com/student/demo",
        "https://user:secret@github.com/student/demo",
        "https://github.com:443/student/demo",
        "https://github.com:/student/demo",
        ROOT + "?ref=main",
        ROOT + "#main",
        ROOT + "?",
        ROOT + "#",
        ROOT + "/tree/main",
        ROOT + "/blob/main/main.py",
        "https://github.com/student",
        "https://github.com/student/..",
        "https://github.com/student/de%2Fmo",
        "https://github.com/student/demo//",
        "https://github.com/\nstudent/demo",
        "https://[invalid",
    ],
)
def test_invalid_github_urls_never_make_a_request(url, mock_client):
    def handler(request):
        pytest.fail("Invalid input made a network request")

    with pytest.raises(InvalidGitHubURL):
        CodeManager(github_client=mock_client(handler)).loadGit(url)


def test_blank_project_override_does_not_request_github(mock_client):
    with pytest.raises(InvalidInput):
        CodeManager(github_client=mock_client(lambda req: pytest.fail("Network called"))).loadGit(
            ROOT, projectName=" "
        )


@pytest.mark.parametrize(
    "destination",
    [
        "http://codeload.github.com/student/demo/zip",
        "https://evil.test/archive",
        "https://api.github.com.evil.test/archive",
        "https://user:password@codeload.github.com/a",
        "https://codeload.github.com:443/a",
        "https://127.0.0.1/a",
        "file:///etc/passwd",
        "https://codeload.github.com/a#fragment",
        "https://[broken",
    ],
)
def test_denied_redirect_hosts_are_not_contacted(destination, mock_client):
    calls = []

    def handler(req):
        calls.append(req)
        if str(req.url) == API:
            return httpx.Response(200, json={"private": False, "default_branch": "develop"})
        return httpx.Response(302, headers={"location": destination})

    with pytest.raises(InvalidGitHubRedirect):
        CodeManager(github_client=mock_client(handler)).loadGit(ROOT)
    assert len(calls) == 2


@pytest.mark.parametrize("location", [None, "https://api.github.com/loop"])
def test_missing_redirect_or_redirect_loop_is_bounded(location, mock_client):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(302, headers={"location": location} if location else {})

    with pytest.raises(InvalidGitHubRedirect):
        CodeManager(
            github_client=mock_client(handler), github_settings=GitHubSettings(max_redirects=2)
        ).loadGit(ROOT)
    assert len(calls) <= 3


@pytest.mark.parametrize(
    ("status", "headers", "error"),
    [
        (404, {}, GitHubUnavailable),
        (401, {}, GitHubUnavailable),
        (403, {}, GitHubUnavailable),
        (500, {}, GitHubUnavailable),
        (429, {}, GitHubRateLimited),
        (403, {"x-ratelimit-remaining": "0"}, GitHubRateLimited),
        (403, {"retry-after": "10"}, GitHubRateLimited),
    ],
)
def test_missing_inaccessible_failed_and_rate_limited_repositories(
    status, headers, error, mock_client
):
    client = mock_client(
        lambda req: httpx.Response(status, headers=headers, text="secret server details")
    )
    manager = CodeManager(github_client=client)
    manager.loadFile(io.BytesIO(b"# valid\n"), fileName="original.py")
    project = manager.getProject()
    with pytest.raises(error) as result:
        manager.loadGit(ROOT)
    assert "secret" not in str(result.value)
    assert manager.getProject() is project


@pytest.mark.parametrize(
    "metadata",
    [
        {"private": True, "default_branch": "main"},
        {"private": False, "visibility": "internal", "default_branch": "main"},
        {"default_branch": "main"},
        [],
        {"private": False, "default_branch": 42},
        {"private": False, "default_branch": "main", "owner": "bad"},
        {"private": False, "default_branch": "main", "name": "../bad"},
    ],
)
def test_private_or_malformed_metadata(metadata, mock_client):
    with pytest.raises(GitHubUnavailable):
        CodeManager(
            github_client=mock_client(lambda req: httpx.Response(200, json=metadata))
        ).loadGit(ROOT)


@pytest.mark.parametrize("branch", [None, ""])
def test_empty_repository_metadata(branch, mock_client):
    with pytest.raises(NoPythonFiles):
        CodeManager(
            github_client=mock_client(
                lambda req: httpx.Response(200, json={"private": False, "default_branch": branch})
            )
        ).loadGit(ROOT)


@pytest.mark.parametrize(
    "scenario", ["empty", "no-python", "bad-zip", "bad-source", "wrong-wrapper", "mixed-roots"]
)
def test_archive_failures_keep_current_project(scenario, make_zip, mock_client):
    entries = {
        "no-python": [("student-demo-abc1234/README.md", b"text")],
        "bad-source": [("student-demo-abc1234/a.py", b""), ("student-demo-abc1234/b.py", b"\xff")],
        "wrong-wrapper": [("user-supplied-folder/main.py", b"")],
        "mixed-roots": [("student-demo-abc1234/main.py", b""), ("other/main.py", b"")],
    }
    data = make_zip(entries.get(scenario, [])) if scenario != "bad-zip" else b"bad zip"

    def handler(req):
        if str(req.url) == API:
            return httpx.Response(200, json={"private": False, "default_branch": "develop"})
        return httpx.Response(404) if scenario == "empty" else httpx.Response(200, content=data)

    manager = CodeManager(github_client=mock_client(handler))
    manager.loadFile(io.BytesIO(b"# original\n"), fileName="good.py")
    project = manager.getProject()
    expected = {
        "empty": NoPythonFiles,
        "no-python": NoPythonFiles,
        "bad-source": InvalidSourceEncoding,
    }.get(scenario, InvalidArchive)
    with pytest.raises(expected):
        manager.loadGit(ROOT)
    assert manager.getProject() is project


@pytest.mark.parametrize(
    "error", [httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout, httpx.ReadTimeout]
)
def test_network_errors_and_inactivity_timeouts(error, mock_client):
    def handler(req):
        raise error("private upstream details", request=req)

    expected = GitHubTimeout if issubclass(error, httpx.TimeoutException) else GitHubUnavailable
    with pytest.raises(expected):
        CodeManager(github_client=mock_client(handler)).loadGit(ROOT)


def test_overall_deadline_cancels_busy_stream(mock_client):
    stream = Chunks(b" " * 200, delay=0.005)
    manager = CodeManager(
        github_client=mock_client(lambda req: httpx.Response(200, stream=stream)),
        github_settings=GitHubSettings(overall_timeout=0.03),
    )
    with pytest.raises(GitHubTimeout):
        manager.loadGit(ROOT)
    assert stream.closed


@pytest.mark.parametrize("declared", [True, False])
def test_download_limit_with_or_without_content_length(declared, make_zip, mock_client):
    data = make_zip([("student-demo-abc1234/main.py", b"# data\n")])

    def handler(req):
        if str(req.url) == API:
            return httpx.Response(200, json={"private": False, "default_branch": "develop"})
        return httpx.Response(
            200, headers={"content-length": str(len(data))} if declared else {}, stream=Chunks(data)
        )

    client = mock_client(handler)
    manager = CodeManager(
        github_client=client, limits=replace(ImportLimits(), max_archive_bytes=len(data))
    )
    assert manager.loadGit(ROOT)[0].fileContent == "# data\n"
    original = manager.getProject()
    manager.limits = replace(ImportLimits(), max_archive_bytes=len(data) - 1)
    with pytest.raises(ImportLimitExceeded):
        manager.loadGit(ROOT)
    assert manager.getProject() is original


@pytest.mark.parametrize(
    "response",
    [
        lambda: httpx.Response(200, content=b"not-json"),
        lambda: httpx.Response(200, headers={"content-length": "invalid"}, content=b"{}"),
        lambda: httpx.Response(200, headers={"content-length": "-1"}, content=b"{}"),
        lambda: httpx.Response(200, headers={"content-encoding": "unsupported"}, content=b"{}"),
    ],
)
def test_bad_upstream_responses_are_safe_errors(response, mock_client):
    with pytest.raises(GitHubUnavailable):
        CodeManager(github_client=mock_client(lambda req: response())).loadGit(ROOT)
