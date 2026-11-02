"""Platform-independent relative paths; no user-controlled path is opened."""

import re


def normalize_relative_path(value: str) -> str:
    """Check dangerous components before removing '.' or repeated separators."""
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Paths must be nonempty and contain no control characters.")
    path = value.replace("\\", "/")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError("Paths must be relative to the project root.")
    components = path.split("/")
    if ".." in components or any(":" in part for part in components):
        raise ValueError("Parent traversal and drive components are not allowed.")
    normalized = "/".join(part for part in components if part not in {"", "."})
    if not normalized:
        raise ValueError("Paths must name a file or directory.")
    return normalized


def upload_basename(value: str) -> str:
    """Discard browser-provided directory prefixes, including Windows fake paths."""
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("An upload must have a valid filename.")
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    return normalize_relative_path(name)
