"""HTTP routes for importing projects and retrieving their original source."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

from .config import GitHubSettings, ImportLimits, RegistryLimits
from .errors import CodeManagerError
from .models import PyProject, SourceFile
from .registry import ProjectRegistry
from .service import CodeManager


# These models describe the request and error JSON exchanged with the UI.
class GitHubImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str
    projectName: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    filePath: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def get_registry(request: Request) -> ProjectRegistry:
    return request.app.state.registry


# Each import request gets a separate manager and its own current project.
def get_code_manager(request: Request) -> CodeManager:
    return CodeManager(
        limits=request.app.state.import_limits,
        github_settings=request.app.state.github_settings,
        github_client=request.app.state.github_client,
    )


# FastAPI supplies these arguments from the current request's app.
Registry = Annotated[ProjectRegistry, Depends(get_registry)]
Manager = Annotated[CodeManager, Depends(get_code_manager)]
ERROR_RESPONSES = {
    status: {"model": ErrorResponse} for status in (400, 404, 413, 422, 429, 502, 503, 504)
}


# Each app owns its registry; blocking imports run in FastAPI's worker threads.
def create_app(
    *,
    import_limits: ImportLimits | None = None,
    registry_limits: RegistryLimits | None = None,
    github_settings: GitHubSettings | None = None,
    github_client: httpx.AsyncClient | None = None,
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            app.state.registry.clear()

    app = FastAPI(title="FlowBridge Code Manager", version="0.1.0", lifespan=lifespan)
    app.state.registry = ProjectRegistry(registry_limits)
    app.state.import_limits = import_limits or ImportLimits()
    app.state.github_settings = github_settings
    app.state.github_client = github_client
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(CodeManagerError)
    async def domain_error(request: Request, error: CodeManagerError) -> JSONResponse:
        return JSONResponse(error.payload(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request fields are missing or invalid. Check the API documentation.",
                }
            },
            status_code=400,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "HTTP_ERROR",
                    "message": "The HTTP request could not be processed.",
                }
            },
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Each import route saves a complete project before returning it to the UI.
    @app.post("/api/projects/file", status_code=201, responses=ERROR_RESPONSES)
    def import_file(
        manager: Manager,
        registry: Registry,
        file: Annotated[UploadFile, File()],
        projectName: Annotated[str | None, Form()] = None,
    ) -> PyProject:
        manager.loadFile(file.file, fileName=file.filename or "", projectName=projectName)
        project = manager.getProject()
        registry.register(project)
        return project

    @app.post("/api/projects/zip", status_code=201, responses=ERROR_RESPONSES)
    def import_zip(
        manager: Manager,
        registry: Registry,
        file: Annotated[UploadFile, File()],
        projectName: Annotated[str | None, Form()] = None,
    ) -> PyProject:
        manager.loadZip(file.file, fileName=file.filename or "", projectName=projectName)
        project = manager.getProject()
        registry.register(project)
        return project

    @app.post("/api/projects/github", status_code=201, responses=ERROR_RESPONSES)
    def import_github(body: GitHubImportRequest, manager: Manager, registry: Registry) -> PyProject:
        manager.loadGit(body.url, projectName=body.projectName)
        project = manager.getProject()
        registry.register(project)
        return project

    @app.get("/api/projects/{projectID}", responses=ERROR_RESPONSES)
    def get_project(projectID: str, registry: Registry) -> PyProject:
        return registry.getProject(projectID)

    @app.get("/api/projects/{projectID}/files/{fileID}", responses=ERROR_RESPONSES)
    def get_file(projectID: str, fileID: str, registry: Registry) -> SourceFile:
        return registry.getSourceFile(projectID, fileID)

    return app


app = create_app()