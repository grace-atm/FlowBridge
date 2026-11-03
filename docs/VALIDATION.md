# Code Manager verification and validation

Module owner: Justin Bean

Initial verification: November 1, 2026 (America/Chicago)

Latest verification: November 3, 2026 (America/Chicago)

Repository base: `jerphan/CodeToChart`, commit `9fdaf1fa0c898b709bbf443647dcb1f7fb2950e7`

Implementation branch: `codex/code-manager`

## Completed verification

The automated suite, lint, and formatting were rerun on November 3 after adding
short function comments and a reading guide. Comparing the Python syntax trees
confirmed that executable code was unchanged. Lock consistency, the real HTTP
smoke test, and the live GitHub import were last checked on November 2. Package
build/installation and the sample CLI checks were completed on November 1.

| Check | Actual result |
| --- | --- |
| Automated pytest suite | **171 passed** |
| Statement coverage of `flowbridge` | **98%**, rounded; not branch coverage |
| Ruff lint | Passed |
| Ruff formatting check | Passed |
| Dependency lock consistency | `uv lock --check --offline` passed |
| Distribution build | Source distribution and wheel built successfully |
| Isolated wheel installation | Passed outside the repository: public imports, legacy aliases, loader, JSON round trip, API import, installed CLI |
| CLI, single sample file | Passed; project `main`, one file `main.py` |
| CLI, sample nested ZIP | Passed; three files, duplicate `main.py` basenames retained |
| Real localhost Uvicorn/HTTP smoke | Passed: health/docs, file/ZIP uploads, original-file retrieval, invalid ZIP error, first project retained |
| Separate live GitHub import | Passed, unauthenticated: `https://github.com/jerphan/CodeToChart`; returned `CodeManager.py` |
| Intended-user validation | **NOT RUN** |

Normal tests use generated/in-memory data, temporary local files, and HTTPX
MockTransport. They require neither GitHub credentials nor internet. The separate
live check exercised GitHub metadata, default-branch archive acquisition, the
actual redirect, generated wrapper removal, source decoding, and project output.
It imported source only; it did not execute the remote `CodeManager.py` scaffold.

The automated cases cover:

- Exact model fields, UUID creation/lifecycle, alias compatibility, lookups, duplicate
  IDs/normalized paths, and complete JSON serialization/deserialization.
- Python/ZIP naming, nested paths, duplicate basenames, case preservation, sorting,
  configurable excluded directories, and non-Python filtering.
- UTF-8, BOM, declared Latin-1, empty source, invalid encodings, tabs/spaces,
  comments, mixed LF/CRLF, final newlines, and syntax errors passed through as text.
- Failed imports preserving the previous project; no imported-source execution.
- Corrupt/no-source ZIPs, unsafe paths (including non-Python/excluded entries),
  NUL/invalid-UTF-8 names, symlinks/special entries, encrypted eligible entries, CRC errors,
  unsupported compression, bounded short reads, and resource limits.
- Exact size/count boundaries and one-byte-over-limit rejections.
- GitHub root URL variants, actual non-main default branches, slash-containing
  branch names, archive redirects, allowed hosts, denied hosts/credentials/ports,
  redirect bounds, API-only tokens, and noninheritance of client auth/cookies.
- Missing/private/empty/no-Python repositories, invalid metadata, network failures,
  rate limits, inactivity timeouts, an overall deadline that cancels a busy stream,
  and bounded archive downloads with or without Content-Length.
- Every API route, exact response fields, uniform domain/validation errors,
  project-scoped retrieval, two-project isolation, failed later imports, capacity,
  real UTF-8 byte accounting, concurrent registration, CORS, and shutdown cleanup.
- CLI file/ZIP imports, module invocation, and useful nonzero JSON error responses.

The `python -m flowbridge` path is additionally exercised in a subprocess, so its
statements are not counted as covered by the parent-process coverage collection.
Coverage is evidence of execution, not a claim that every possible input is supported.

## Reproduce the checks

From the repository root, with Python 3.12:

```powershell
uv sync --locked
uv run pytest -q --cov=flowbridge --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv lock --check
uv build
uv run python scripts/smoke_api.py

uv run flowbridge-code file examples/sample_project/app/main.py
uv run python -c "import shutil; shutil.make_archive('demo-project', 'zip', 'examples/sample_project')"
uv run flowbridge-code zip demo-project.zip --project-name "Nested demo"

# Optional separate internet-dependent check; never part of pytest:
uv run flowbridge-code github https://github.com/jerphan/CodeToChart
```

The verified environment was Windows with CPython 3.12.14, uv 0.11.28, and the
versions recorded in `uv.lock`. The current lock emits one upstream
`StarletteDeprecationWarning` about its HTTPX TestClient compatibility adapter.
Tests pass; this is a dependency-maintenance note, not an import failure. No new
HTTPX2 dependency was added to this HTTPX-based module.

The Windows execution sandbox blocked its default temporary-directory setup and
Python's local async event-loop socket pair. Verification used a workspace-owned
test temporary directory and an execution context permitting the loopback socket.
The tests' GitHub transport stayed mocked. These were execution-environment issues;
no sandbox-specific workaround was added to application code.

## Intended-user validation checklist

Status for every row below is **NOT RUN**. The completed developer checks above
are not participant validation. Record actual observations before changing status.

Participant name/role: ____________________  Date: ____________________

Environment/browser: ____________________  Facilitator: ____________________

Start the API and open `http://127.0.0.1:8000/docs`. Create the sample ZIP using the
command above. Use the returned IDs rather than substituting guessed filenames.

| Scenario | Expected behavior | Status | Observed result / feedback |
| --- | --- | --- | --- |
| Upload `examples/sample_project/app/main.py` using `/api/projects/file` | 201; project with one SourceFile, correct basename and original source | NOT RUN | ____________________ |
| Upload `demo-project.zip` using `/api/projects/zip` | 201; exactly three sorted nested paths; two distinct `main.py` file IDs | NOT RUN | ____________________ |
| Import a small public repository using `/api/projects/github` | 201; default-branch Python files; only generated GitHub wrapper removed | NOT RUN | ____________________ |
| Upload a text file to the Python route or invalid bytes named `bad.zip` to the ZIP route | Clear 400 JSON error with a useful message; earlier projects still retrievable | NOT RUN | ____________________ |
| Retrieve the ZIP project's `tests/main.py` using its project/file IDs | Returns its original content, not `app/main.py`; stable IDs | NOT RUN | ____________________ |
| Try the same file ID under a different project | 404; no cross-project lookup | NOT RUN | ____________________ |

Were the upload and error messages understandable? ____________________

Could the participant identify the two `main.py` files? ____________________

Was any content/formatting unexpected? ____________________

Requested improvements: ____________________

Follow-up action and owner: ____________________

No participants, feedback, screenshots, or user-validation success are claimed in
this handoff. Any later group report should retain that distinction.

## Suggested module demo, approximately 5-6 minutes

1. **0:00-0:45:** Show the module boundary and exact project/source contract.
2. **0:45-1:30:** Upload one `.py` file in FastAPI docs and show preserved source.
3. **1:30-2:45:** Upload the nested sample ZIP; compare both `main.py` paths/IDs.
4. **2:45-3:45:** Import the small public repository and show the same JSON shape.
5. **3:45-4:30:** Trigger an invalid ZIP/URL error, then retrieve an earlier project.
6. **4:30-5:30:** Retrieve the correct original file by IDs and explain the parser
   and source-mapping handoff; show the actual automated test result.

This demonstrates Code Manager. A full FlowBridge diagram demo still needs the
team's parser, graph, mapping, and UI integration. Account for live GitHub access
and rate limits before presenting; keep the local ZIP scenario available.

## Current limitations and remaining work

- Registry data is process-local and disappears on shutdown/restart; one-worker
  demo only. Capacity errors are explicit rather than silently evicting projects.
- Imports support documented size/count budgets and public default branches.
  Submodules, Git LFS downloads, private repositories, and nested archives are not fetched.
- No parser/UI/source-mapping/diagram integration is claimed complete. The handoff
  documents the next calls and ownership boundaries.
- Intended-user validation is still required. Fill in the checklist with observed
  results and actual feedback before writing Stage 3 user-validation conclusions.
- Review the `codex/code-manager` branch before merging it into `main`. Keep the
  exact shared contract when connecting the other team modules.
