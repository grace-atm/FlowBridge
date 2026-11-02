import httpx
import pytest
from fastapi.testclient import TestClient

from flowbridge.api import create_app
from flowbridge.config import ImportLimits, RegistryLimits
from flowbridge.errors import ProjectNotFound


def upload(client, content=b"print('hello')\r\n", filename="main.py", **data):
    return client.post(
        "/api/projects/file", files={"file": (filename, content, "text/x-python")}, data=data
    )


def test_health_docs_schema_file_import_and_original_retrieval():
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
        assert set(schema["components"]["schemas"]["PyProject"]["properties"]) == {
            "projectID",
            "projectName",
            "files",
        }
        assert set(schema["components"]["schemas"]["SourceFile"]["properties"]) == {
            "fileID",
            "fileName",
            "filePath",
            "fileContent",
        }
        result = upload(client, projectName="UI project")
        assert result.status_code == 201
        project = result.json()
        assert set(project) == {"projectID", "projectName", "files"}
        assert project["projectName"] == "UI project"
        assert project["files"][0]["fileContent"] == "print('hello')\r\n"
        path = f"/api/projects/{project['projectID']}"
        assert client.get(path).json() == project
        assert (
            client.get(f"{path}/files/{project['files'][0]['fileID']}").json()
            == project["files"][0]
        )


def test_nested_zip_upload_and_duplicate_basename_lookup(make_zip):
    data = make_zip([("tests/main.py", b"# tests"), ("app/main.py", b"# app")])
    with TestClient(create_app()) as client:
        result = client.post(
            "/api/projects/zip", files={"file": ("nested.zip", data, "application/zip")}
        )
        assert result.status_code == 201
        project = result.json()
        assert project["projectName"] == "nested"
        assert [f["filePath"] for f in project["files"]] == ["app/main.py", "tests/main.py"]
        for file in project["files"]:
            response = client.get(f"/api/projects/{project['projectID']}/files/{file['fileID']}")
            assert response.json() == file


def test_github_import_route_uses_real_loader(make_zip, mock_client):
    data = make_zip([("student-demo-abc1234/src/main.py", b"# github\r\n")])
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"private": False, "default_branch": "develop"})
        if len(requests) == 2:
            return httpx.Response(
                302,
                headers={"location": "https://codeload.github.com/student/demo/legacy.zip/develop"},
            )
        return httpx.Response(200, content=data)

    with TestClient(create_app(github_client=mock_client(handler))) as client:
        response = client.post(
            "/api/projects/github",
            json={"url": "https://github.com/student/demo", "projectName": "Repository"},
        )
        assert response.status_code == 201
        project = response.json()
        assert project["projectName"] == "Repository"
        assert project["files"][0]["filePath"] == "src/main.py"
        assert project["files"][0]["fileContent"] == "# github\r\n"
        assert client.get(f"/api/projects/{project['projectID']}").json() == project


def test_project_isolation_and_failed_second_import_keeps_first():
    with TestClient(create_app()) as client:
        first = upload(client, b"# one", "main.py").json()
        second = upload(client, b"# two", "main.py").json()
        first_path = f"/api/projects/{first['projectID']}"
        second_path = f"/api/projects/{second['projectID']}"
        assert first["projectID"] != second["projectID"]
        assert first["files"][0]["fileID"] != second["files"][0]["fileID"]
        assert client.get(first_path).json() == first
        assert client.get(second_path).json() == second
        assert client.get(f"{first_path}/files/{second['files'][0]['fileID']}").status_code == 404
        failure = client.post("/api/projects/zip", files={"file": ("bad.zip", b"not zip")})
        assert failure.status_code == 400
        assert client.get(first_path).json() == first
        assert client.get(second_path).json() == second


@pytest.mark.parametrize(
    ("operation", "expected_status", "expected_code"),
    [
        (lambda c: upload(c, b"", "bad.txt"), 400, "INVALID_INPUT"),
        (lambda c: upload(c, b"\xff", "bad.py"), 400, "INVALID_SOURCE_ENCODING"),
        (lambda c: upload(c, b"", "good.py", projectName=" "), 400, "INVALID_INPUT"),
        (
            lambda c: c.post("/api/projects/zip", files={"file": ("bad.zip", b"not zip")}),
            400,
            "INVALID_ARCHIVE",
        ),
        (lambda c: c.post("/api/projects/file"), 400, "INVALID_REQUEST"),
        (
            lambda c: c.post("/api/projects/github", json={"url": 123, "secret": "must not leak"}),
            400,
            "INVALID_REQUEST",
        ),
        (
            lambda c: c.post(
                "/api/projects/github",
                content="not-json",
                headers={"content-type": "application/json"},
            ),
            400,
            "INVALID_REQUEST",
        ),
        (
            lambda c: c.post("/api/projects/github", json={"url": "https://example.com/x/y"}),
            400,
            "INVALID_GITHUB_URL",
        ),
        (lambda c: c.get("/api/projects/missing"), 404, "PROJECT_NOT_FOUND"),
        (lambda c: c.get("/api/projects/missing/files/missing"), 404, "PROJECT_NOT_FOUND"),
        (lambda c: c.get("/unknown"), 404, "HTTP_ERROR"),
    ],
)
def test_consistent_error_responses(operation, expected_status, expected_code):
    with TestClient(create_app()) as client:
        result = operation(client)
        assert result.status_code == expected_status
        body = result.json()
        assert set(body) == {"error"}
        assert body["error"]["code"] == expected_code
        assert isinstance(body["error"]["message"], str)
        assert set(body["error"]) <= {"code", "message", "filePath"}
        assert "must not leak" not in result.text
        assert "Traceback" not in result.text


def test_missing_file_and_source_error_safe_path():
    with TestClient(create_app()) as client:
        project = upload(client).json()
        response = client.get(f"/api/projects/{project['projectID']}/files/not-a-file")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "FILE_NOT_FOUND"
        response = upload(client, b"\xff", r"C:\secret\bad.py")
        assert response.json()["error"]["filePath"] == "bad.py"
        assert "secret" not in response.text


def test_limit_no_python_and_full_registry_statuses(make_zip):
    app = create_app(
        import_limits=ImportLimits(max_file_bytes=4), registry_limits=RegistryLimits(max_projects=1)
    )
    with TestClient(app) as client:
        over = upload(client, b"12345")
        assert over.status_code == 413 and over.json()["error"]["code"] == "IMPORT_LIMIT_EXCEEDED"
        no_source = client.post("/api/projects/zip", files={"file": ("empty.zip", make_zip([]))})
        assert (
            no_source.status_code == 422 and no_source.json()["error"]["code"] == "NO_PYTHON_FILES"
        )
        first = upload(client, b"1234").json()
        full = upload(client, b"")
        assert (
            full.status_code == 503 and full.json()["error"]["code"] == "REGISTRY_CAPACITY_EXCEEDED"
        )
        assert client.get(f"/api/projects/{first['projectID']}").json() == first


def test_registry_counts_actual_utf8_text_bytes():
    with TestClient(
        create_app(registry_limits=RegistryLimits(max_projects=10, max_text_bytes=4))
    ) as client:
        assert upload(client, "é".encode()).status_code == 201
        assert upload(client, "é".encode()).status_code == 201
        assert upload(client, b"x").status_code == 503


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        ("rate", 429, "GITHUB_RATE_LIMITED"),
        ("upstream", 502, "GITHUB_UNAVAILABLE"),
        ("timeout", 504, "GITHUB_TIMEOUT"),
    ],
)
def test_github_error_statuses_preserve_retained_project(
    failure, expected_status, expected_code, mock_client
):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret token", request=request)
        return httpx.Response(429 if failure == "rate" else 500, text="private details")

    with TestClient(create_app(github_client=mock_client(handler))) as client:
        first = upload(client).json()
        error = client.post("/api/projects/github", json={"url": "https://github.com/student/demo"})
        assert error.status_code == expected_status
        assert error.json()["error"]["code"] == expected_code
        assert "secret token" not in error.text and "private details" not in error.text
        assert client.get(f"/api/projects/{first['projectID']}").json() == first


def test_cors_explicit_local_origins_and_shutdown_cleanup():
    app = create_app()
    with TestClient(app) as client:
        project = upload(client).json()
        headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
        allowed = client.options("/api/projects/file", headers=headers)
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        denied = client.options(
            "/api/projects/file", headers=headers | {"Origin": "https://unconfigured.example"}
        )
        assert "access-control-allow-origin" not in denied.headers
    with pytest.raises(ProjectNotFound):
        app.state.registry.getProject(project["projectID"])
