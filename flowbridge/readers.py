"""Read uploaded bytes and Python source without extracting ZIPs to disk."""

import io
import re
import stat
import tokenize
import zipfile
import zlib
from typing import BinaryIO

from .config import ImportLimits
from .errors import (
    DuplicateFile,
    ImportLimitExceeded,
    InvalidArchive,
    InvalidInput,
    InvalidSourceEncoding,
    NoPythonFiles,
)
from .models import SourceFile
from .paths import normalize_relative_path

CHUNK_SIZE = 64 * 1024


# Read one extra byte to detect input that exceeds the limit.
def read_bounded(stream: BinaryIO, limit: int, *, filePath: str | None = None) -> bytes:
    data = bytearray()
    while True:
        try:
            chunk = stream.read(min(CHUNK_SIZE, limit - len(data) + 1))
        except (OSError, ValueError):
            raise InvalidInput("The uploaded data could not be read.", filePath=filePath) from None
        if not isinstance(chunk, bytes):
            raise InvalidInput("A readable binary stream is required.")
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > limit:
            raise ImportLimitExceeded("Input exceeds the configured byte limit.", filePath=filePath)


# Decode Python's declared encoding while keeping spacing and line endings.
def decode_source(data: bytes, filePath: str) -> SourceFile:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        content = data.decode(encoding, errors="strict")
        # Escape-based codecs can leave lone surrogates that cannot be stored as UTF-8.
        content.encode("utf-8", errors="strict")
    except (SyntaxError, UnicodeError, LookupError):
        raise InvalidSourceEncoding(
            "Python source has an unknown, conflicting, or invalid encoding.", filePath=filePath
        ) from None
    return SourceFile(fileName=filePath.rsplit("/", 1)[-1], filePath=filePath, fileContent=content)


# Read ZIP entries in memory so archive paths are never extracted onto the server.
def read_zip(
    data: bytes, limits: ImportLimits, *, github_prefix: str | None = None
) -> list[SourceFile]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_entries:
                raise ImportLimitExceeded("Archive has too many entries.")
            if sum(entry.file_size for entry in entries) > limits.max_uncompressed_bytes:
                raise ImportLimitExceeded("Archive's declared uncompressed size is too large.")

            # Check every entry's path before choosing which files to read.
            paths: list[tuple[zipfile.ZipInfo, str]] = []
            seen: set[str] = set()
            for entry in entries:
                try:
                    path = normalize_relative_path(entry.orig_filename)
                except ValueError:
                    raise InvalidArchive("Archive contains an unsafe relative path.") from None
                if path in seen:
                    raise DuplicateFile(
                        "Archive contains duplicate normalized paths.", filePath=path
                    )
                seen.add(path)
                paths.append((entry, path))

            # Remove GitHub's generated root folder; keep folders in uploaded ZIPs.
            wrapper: str | None = None
            if github_prefix is not None and paths:
                wrapper = paths[0][1].split("/", 1)[0]
                if not re.fullmatch(re.escape(github_prefix) + r"[0-9a-fA-F]{7,64}", wrapper):
                    raise InvalidArchive("GitHub archive has an unexpected root directory.")
                if any(path.split("/", 1)[0] != wrapper for _, path in paths):
                    raise InvalidArchive("GitHub archive has inconsistent root directories.")

            selected: list[tuple[zipfile.ZipInfo, str]] = []
            for entry, path in paths:
                if wrapper is not None:
                    if path == wrapper:
                        if not entry.is_dir():
                            raise InvalidArchive("GitHub archive root must be a directory.")
                        continue
                    path = path[len(wrapper) + 1 :]
                if entry.is_dir():
                    continue
                components = path.split("/")
                if any(part in limits.excluded_directories for part in components[:-1]):
                    continue
                if not path.lower().endswith(".py"):
                    continue
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise InvalidArchive(
                        "Eligible Python entry is not a regular file.", filePath=path
                    )
                if entry.flag_bits & 1:
                    raise InvalidArchive(
                        "Encrypted Python entries are not supported.", filePath=path
                    )
                if entry.file_size > limits.max_file_bytes:
                    raise ImportLimitExceeded("Python file is too large.", filePath=path)
                selected.append((entry, path))
            if not selected:
                raise NoPythonFiles("Archive contains no eligible Python files.")
            if len(selected) > limits.max_files:
                raise ImportLimitExceeded("Project has too many Python files.")
            if sum(entry.file_size for entry, _ in selected) > limits.max_source_bytes:
                raise ImportLimitExceeded("Project's declared Python source size is too large.")

            # Read the selected files in path order and check their actual byte sizes.
            files: list[SourceFile] = []
            actual_total = 0
            for entry, path in sorted(selected, key=lambda item: item[1]):
                with archive.open(entry) as source:
                    content = read_bounded(
                        source,
                        min(limits.max_file_bytes, limits.max_source_bytes - actual_total),
                        filePath=path,
                    )
                actual_total += len(content)
                files.append(decode_source(content, path))
            return files
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
        UnicodeError,
    ):
        raise InvalidArchive(
            "ZIP is corrupt, encrypted, or uses unsupported compression."
        ) from None
