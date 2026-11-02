"""Small application-owned registry with atomic capacity checks and source access."""

from threading import Lock

from .config import RegistryLimits
from .errors import DuplicateFile, ProjectNotFound, RegistryCapacityExceeded
from .models import PyProject, SourceFile


class ProjectRegistry:
    def __init__(self, limits: RegistryLimits | None = None) -> None:
        self.limits = limits or RegistryLimits()
        self._projects: dict[str, PyProject] = {}
        self._text_bytes = 0
        self._lock = Lock()

    def register(self, project: PyProject) -> None:
        """Snapshot a validated candidate so later caller mutations cannot bypass capacity."""
        snapshot = PyProject.model_validate_json(project.model_dump_json())
        size = sum(len(file.fileContent.encode("utf-8")) for file in snapshot.files)
        with self._lock:
            if snapshot.projectID in self._projects:
                raise DuplicateFile("A project with that ID is already registered.")
            if (
                len(self._projects) >= self.limits.max_projects
                or self._text_bytes + size > self.limits.max_text_bytes
            ):
                raise RegistryCapacityExceeded(
                    "Demo project storage is full. Restart the server to clear retained projects."
                )
            self._projects[snapshot.projectID] = snapshot
            self._text_bytes += size

    def getProject(self, projectID: str) -> PyProject:
        with self._lock:
            project = self._find(projectID)
            return project.model_copy(deep=True)

    def getSourceFile(self, projectID: str, fileID: str) -> SourceFile:
        with self._lock:
            return self._find(projectID).getFileByID(fileID)

    def _find(self, projectID: str) -> PyProject:
        project = self._projects.get(projectID)
        if project is None:
            raise ProjectNotFound("No retained project has that ID.")
        return project

    def clear(self) -> None:
        with self._lock:
            self._projects.clear()
            self._text_bytes = 0
