# These models are shared with the parser and source-mapping layer.

from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import DuplicateFile, FileNotFoundInProject
from .paths import normalize_relative_path


def _uuid_string(value: str) -> str:
    return str(UUID(value))


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    fileID: str = Field(default_factory=lambda: str(uuid4()))
    fileName: str
    filePath: str
    fileContent: str

    @field_validator("fileID")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _uuid_string(value)

    @field_validator("filePath")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return normalize_relative_path(value)

    @model_validator(mode="after")
    def matching_basename(self) -> Self:
        if self.fileName != self.filePath.rsplit("/", 1)[-1]:
            raise ValueError("fileName must be the basename of filePath.")
        return self


class PyProject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    projectID: str = Field(default_factory=lambda: str(uuid4()))
    projectName: str
    files: list[SourceFile] = Field(default_factory=list)

    @field_validator("projectID")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _uuid_string(value)

    @field_validator("projectName")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("projectName must be nonblank.")
        return value.strip()

    @model_validator(mode="after")
    def unique_files(self) -> Self:
        ids = [file.fileID for file in self.files]
        paths = [file.filePath for file in self.files]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("A project cannot contain duplicate file IDs or normalized paths.")
        return self

    def addFile(self, file: SourceFile) -> None:
        if any(item.fileID == file.fileID or item.filePath == file.filePath for item in self.files):
            raise DuplicateFile(
                "File ID or path already exists in this project.", filePath=file.filePath
            )
        self.files.append(file)

    def getFileByID(self, fileID: str) -> SourceFile:
        for file in self.files:
            if file.fileID == fileID:
                return file
        raise FileNotFoundInProject("No file with that ID exists in this project.")

    def getFileID(self, fileID: str) -> SourceFile:
        # The UML name returns a file object, despite being called getFileID.
        return self.getFileByID(fileID)


# Keep the names from the UML as aliases.
pyProject = PyProject
sourceFile = SourceFile
