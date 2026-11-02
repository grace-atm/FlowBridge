"""Configurable demo budgets. Sizes are bytes, times are seconds."""

from dataclasses import dataclass, field

MiB = 1024 * 1024


@dataclass(frozen=True)
class ImportLimits:
    max_file_bytes: int = MiB
    max_archive_bytes: int = 20 * MiB
    max_source_bytes: int = 20 * MiB
    max_uncompressed_bytes: int = 50 * MiB
    max_entries: int = 10_000
    max_files: int = 1_000
    excluded_directories: frozenset[str] = frozenset(
        {".git", ".venv", "venv", "__pycache__", "node_modules", "__MACOSX"}
    )

    def __post_init__(self) -> None:
        for name in (
            "max_file_bytes",
            "max_archive_bytes",
            "max_source_bytes",
            "max_uncompressed_bytes",
            "max_entries",
            "max_files",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class GitHubSettings:
    token: str | None = field(default=None, repr=False)
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    overall_timeout: float = 60.0
    max_redirects: int = 3

    def __post_init__(self) -> None:
        if min(self.connect_timeout, self.read_timeout, self.overall_timeout) <= 0:
            raise ValueError("GitHub timeouts must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")


@dataclass(frozen=True)
class RegistryLimits:
    max_projects: int = 10
    max_text_bytes: int = 100 * MiB

    def __post_init__(self) -> None:
        if min(self.max_projects, self.max_text_bytes) < 1:
            raise ValueError("Registry capacities must be positive")
