from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from flowbridge import PyProject, SourceFile
from flowbridge.config import RegistryLimits
from flowbridge.errors import DuplicateFile, RegistryCapacityExceeded
from flowbridge.registry import ProjectRegistry


def project(content="abc"):
    return PyProject(
        projectName="Demo",
        files=[SourceFile(fileName="main.py", filePath="main.py", fileContent=content)],
    )


def test_registry_retains_isolated_validated_snapshots():
    registry = ProjectRegistry(RegistryLimits(max_projects=2, max_text_bytes=3))
    original = project()
    registry.register(original)
    file_id = original.files[0].fileID
    original.files.clear()
    retrieved = registry.getProject(original.projectID)
    assert registry.getSourceFile(original.projectID, file_id).fileContent == "abc"
    retrieved.files.clear()
    assert len(registry.getProject(original.projectID).files) == 1
    with pytest.raises(RegistryCapacityExceeded):
        registry.register(project("x"))
    registry.clear()
    registry.register(project("abc"))


def test_duplicate_project_registration_rejected_without_consuming_capacity():
    registry = ProjectRegistry(RegistryLimits(max_projects=2))
    first = project()
    registry.register(first)
    with pytest.raises(DuplicateFile):
        registry.register(first)
    registry.register(project())


def test_concurrent_capacity_check_and_register_is_atomic():
    registry = ProjectRegistry(RegistryLimits(max_projects=1))
    barrier = Barrier(2)

    def register_one():
        candidate = project()
        barrier.wait(timeout=5)
        try:
            registry.register(candidate)
        except RegistryCapacityExceeded:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register_one(), range(2)))
    assert sorted(results) == [False, True]
