"""Synchronous Code Manager service, independent of FastAPI and the parser."""

import asyncio
import os
from time import monotonic
from typing import BinaryIO

import httpx

from .config import GitHubSettings, ImportLimits
from .errors import FileNotFoundInProject, GitHubTimeout, InvalidInput, NoProjectLoaded
from .github import GitHubDownloader, parse_repository_url
from .models import PyProject, SourceFile
from .paths import normalize_relative_path, upload_basename
from .readers import decode_source, read_bounded, read_zip


class CodeManager:
    """Each successful load replaces project; every failed load leaves it intact.

    This synchronous class belongs to one project context/coordinator. Async
    applications should call blocking loaders in a worker thread. API requests
    each receive a separate manager; completed projects go into the registry.
    """

    def __init__(
        self,
        *,
        limits: ImportLimits | None = None,
        github_settings: GitHubSettings | None = None,
        github_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.project: PyProject | None = None
        self.limits = limits or ImportLimits()
        self.github_settings = github_settings or GitHubSettings(
            token=os.environ.get("GITHUB_TOKEN")
        )
        self._github_client = github_client

    @staticmethod
    def _display_name(override: str | None, default: str) -> str:
        name = default if override is None else override
        if not name.strip():
            raise InvalidInput("projectName must be nonblank when provided.")
        return name.strip()

    @staticmethod
    def _filename(value: str, extension: str) -> str:
        try:
            name = upload_basename(value)
        except ValueError:
            raise InvalidInput("Upload must have a valid filename.") from None
        if not name.lower().endswith(extension):
            raise InvalidInput(f"Upload must have a {extension} filename.")
        return name

    def _commit(self, files: list[SourceFile], name: str) -> list[SourceFile]:
        candidate = PyProject(projectName=name, files=files)
        self.project = candidate
        return candidate.files

    def loadFile(
        self, file: BinaryIO, *, fileName: str, projectName: str | None = None
    ) -> list[SourceFile]:
        name = self._filename(fileName, ".py")
        display = self._display_name(projectName, name[:-3])
        content = read_bounded(
            file, min(self.limits.max_file_bytes, self.limits.max_source_bytes), filePath=name
        )
        return self._commit([decode_source(content, name)], display)

    def loadZip(
        self, file: BinaryIO, *, fileName: str, projectName: str | None = None
    ) -> list[SourceFile]:
        name = self._filename(fileName, ".zip")
        display = self._display_name(projectName, name[:-4])
        content = read_bounded(file, self.limits.max_archive_bytes)
        return self._commit(read_zip(content, self.limits), display)

    def loadGit(self, url: str, *, projectName: str | None = None) -> list[SourceFile]:
        _, repository = parse_repository_url(url)
        # Validate overrides before performing network work.
        self._display_name(projectName, repository)
        start = monotonic()
        downloader = GitHubDownloader(self.limits, self.github_settings, self._github_client)
        archive = asyncio.run(downloader.fetch(url))
        files = read_zip(archive.data, self.limits, github_prefix=archive.wrapper_prefix)
        if monotonic() - start > self.github_settings.overall_timeout:
            raise GitHubTimeout("GitHub import exceeded the overall deadline.")
        return self._commit(files, self._display_name(projectName, archive.name))

    def getProject(self) -> PyProject:
        if self.project is None:
            raise NoProjectLoaded("No project has been imported yet.")
        return self.project

    def getSourceFile(self, fileID: str) -> SourceFile:
        return self.getProject().getFileByID(fileID)

    def getSourceFileByPath(self, filePath: str) -> SourceFile:
        project = self.getProject()
        try:
            path = normalize_relative_path(filePath)
        except ValueError:
            raise InvalidInput("Source lookup requires a safe project-relative path.") from None
        for file in project.files:
            if file.filePath == path:
                return file
        raise FileNotFoundInProject("No file with that path exists in this project.", filePath=path)
