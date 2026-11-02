"""Public, source-free errors shared by the service and HTTP adapter."""


class CodeManagerError(Exception):
    code = "INVALID_INPUT"
    status = 400

    def __init__(self, message: str, *, filePath: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.filePath = filePath

    def payload(self) -> dict[str, dict[str, str]]:
        error = {"code": self.code, "message": self.message}
        if self.filePath is not None:
            error["filePath"] = self.filePath
        return {"error": error}


class InvalidInput(CodeManagerError):
    pass


class InvalidArchive(CodeManagerError):
    code = "INVALID_ARCHIVE"


class InvalidSourceEncoding(CodeManagerError):
    code = "INVALID_SOURCE_ENCODING"


class DuplicateFile(CodeManagerError):
    code = "DUPLICATE_FILE"


class NoProjectLoaded(CodeManagerError):
    code = "NO_PROJECT_LOADED"
    status = 404


class FileNotFoundInProject(CodeManagerError):
    code = "FILE_NOT_FOUND"
    status = 404


class ProjectNotFound(CodeManagerError):
    code = "PROJECT_NOT_FOUND"
    status = 404


class ImportLimitExceeded(CodeManagerError):
    code = "IMPORT_LIMIT_EXCEEDED"
    status = 413


class NoPythonFiles(CodeManagerError):
    code = "NO_PYTHON_FILES"
    status = 422


class InvalidGitHubURL(CodeManagerError):
    code = "INVALID_GITHUB_URL"


class GitHubUnavailable(CodeManagerError):
    code = "GITHUB_UNAVAILABLE"
    status = 502


class InvalidGitHubRedirect(GitHubUnavailable):
    code = "INVALID_GITHUB_REDIRECT"


class GitHubRateLimited(CodeManagerError):
    code = "GITHUB_RATE_LIMITED"
    status = 429


class GitHubTimeout(CodeManagerError):
    code = "GITHUB_TIMEOUT"
    status = 504


class RegistryCapacityExceeded(CodeManagerError):
    code = "REGISTRY_CAPACITY_EXCEEDED"
    status = 503
