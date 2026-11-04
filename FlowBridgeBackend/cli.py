"""Runnable demonstration using the same real loaders as the API."""

import argparse
import json
import sys
from pathlib import Path

from .errors import CodeManagerError, InvalidInput
from .service import CodeManager


# Run one import from the terminal and print its project JSON.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Python source and print the project JSON.")
    parser.add_argument("kind", choices=("file", "zip", "github"))
    parser.add_argument("source", help="Local file/ZIP path, or public GitHub repository root URL")
    parser.add_argument("--project-name", default=None)
    args = parser.parse_args(argv)
    manager = CodeManager()
    try:
        if args.kind == "github":
            manager.loadGit(args.source, projectName=args.project_name)
        else:
            path = Path(args.source)
            try:
                with path.open("rb") as stream:
                    loader = manager.loadFile if args.kind == "file" else manager.loadZip
                    loader(stream, fileName=path.name, projectName=args.project_name)
            except OSError:
                raise InvalidInput("The supplied local input file could not be opened.") from None
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(manager.getProject().model_dump_json(indent=2))
        return 0
    except CodeManagerError as error:
        print(json.dumps(error.payload()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())