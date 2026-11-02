"""Optional real localhost smoke test. No live GitHub calls or source execution."""

import io
import json
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryFile

import httpx


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("app/main.py", "# app\r\n")
        archive.writestr("tests/main.py", "# tests\n")

    with TemporaryFile() as server_output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "flowbridge.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=root,
            stdout=server_output,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=base, timeout=5, trust_env=False) as client:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        health = client.get("/health")
                        health.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if time.monotonic() >= deadline or process.poll() is not None:
                            raise RuntimeError("Local API did not become ready.") from None
                        time.sleep(0.1)
                assert health.json() == {"status": "ok"}
                assert client.get("/docs").status_code == 200
                response = client.post(
                    "/api/projects/file", files={"file": ("demo.py", b"if True:\r\n\tpass\r\n")}
                )
                assert response.status_code == 201
                first = response.json()
                assert first["files"][0]["fileContent"] == "if True:\r\n\tpass\r\n"
                response = client.post(
                    "/api/projects/zip", files={"file": ("demo.zip", archive_bytes.getvalue())}
                )
                assert response.status_code == 201
                second = response.json()
                assert [file["filePath"] for file in second["files"]] == [
                    "app/main.py",
                    "tests/main.py",
                ]
                file = second["files"][1]
                assert (
                    client.get(f"/api/projects/{second['projectID']}/files/{file['fileID']}").json()
                    == file
                )
                bad = client.post("/api/projects/zip", files={"file": ("bad.zip", b"not-zip")})
                assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_ARCHIVE"
                assert client.get(f"/api/projects/{first['projectID']}").json() == first
                print(
                    json.dumps(
                        {
                            "result": "PASS",
                            "checks": [
                                "health",
                                "docs",
                                "file upload",
                                "nested ZIP",
                                "original file retrieval",
                                "invalid ZIP",
                                "retained first project",
                            ],
                        }
                    )
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
