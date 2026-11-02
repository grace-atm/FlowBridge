import io
from uuid import UUID

import pytest
from pydantic import ValidationError

import CodeManager as legacy
from flowbridge import CodeManager, PyProject, SourceFile, pyProject, sourceFile
from flowbridge.errors import DuplicateFile, FileNotFoundInProject


def source(path="main.py", **kwargs):
    return SourceFile(
        fileName=path.replace("\\", "/").rsplit("/", 1)[-1],
        filePath=path,
        fileContent="\t# original\r\n\n",
        **kwargs,
    )


def test_aliases_are_the_same_classes():
    assert legacy.CodeManager is CodeManager
    assert legacy.pyProject is pyProject is PyProject
    assert legacy.sourceFile is sourceFile is SourceFile


def test_complete_json_round_trip_and_lookup():
    manager = CodeManager()
    files = manager.loadFile(io.BytesIO(b"if True:\r\n\tpass\r\n\n"), fileName="main.py")
    project = manager.getProject()
    before = project.model_dump()
    restored = PyProject.model_validate_json(project.model_dump_json())
    assert restored.model_dump() == before
    assert set(before) == {"projectID", "projectName", "files"}
    assert set(before["files"][0]) == {"fileID", "fileName", "filePath", "fileContent"}
    assert restored.getFileByID(files[0].fileID) is restored.files[0]
    assert restored.getFileID(files[0].fileID) is restored.files[0]
    assert restored.files[0].fileContent == "if True:\r\n\tpass\r\n\n"
    assert UUID(restored.projectID).version == 4
    assert UUID(restored.files[0].fileID).version == 4
    for _ in range(3):
        assert manager.getSourceFile(files[0].fileID) is files[0]
        assert manager.getProject().model_dump() == before


def test_add_file_and_independent_default_lists():
    first, second = PyProject(projectName="One"), PyProject(projectName="Two")
    file = source()
    assert first.addFile(file) is None
    assert first.getFileByID(file.fileID) is file
    assert second.files == []
    with pytest.raises(FileNotFoundInProject):
        second.getFileByID(file.fileID)


@pytest.mark.parametrize("duplicate", ["id", "path"])
def test_duplicate_ids_and_normalized_paths_on_add_and_deserialization(duplicate):
    first = source("app/main.py")
    second = (
        source("tests/main.py", fileID=first.fileID)
        if duplicate == "id"
        else source("app\\.\\main.py")
    )
    project = PyProject(projectName="Demo", files=[first])
    with pytest.raises(DuplicateFile):
        project.addFile(second)
    with pytest.raises(ValidationError):
        PyProject(projectName="Demo", files=[first, second])
    data = project.model_dump()
    data["files"].append(second.model_dump())
    with pytest.raises(ValidationError):
        PyProject.model_validate(data)
    assert project.files == [first]


@pytest.mark.parametrize(
    "change",
    [
        {"fileID": "bad-id"},
        {"fileName": "other.py"},
        {"filePath": "../main.py"},
        {"filePath": "/main.py"},
        {"content": "wrong field"},
    ],
)
def test_model_contract_rejects_bad_data(change):
    data = source().model_dump() | change
    with pytest.raises(ValidationError):
        SourceFile.model_validate(data)


def test_source_is_frozen_and_project_name_is_required():
    file = source()
    with pytest.raises(ValidationError):
        file.fileContent = "changed"
    with pytest.raises(ValidationError):
        PyProject(projectName="  ")
    with pytest.raises(ValidationError):
        PyProject(projectID="not-a-uuid", projectName="Demo")
