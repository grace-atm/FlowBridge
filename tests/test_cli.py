import json
import subprocess
import sys

import pytest

from flowbridge.cli import main


@pytest.mark.parametrize("kind", ["file", "zip"])
def test_cli_imports_actual_supplied_input(kind, tmp_path, make_zip, capsys):
    content = b"if True:\r\n\tpass\r\n"
    path = tmp_path / ("main.py" if kind == "file" else "project.zip")
    path.write_bytes(content if kind == "file" else make_zip([("nested/main.py", content)]))
    assert main([kind, str(path), "--project-name", "CLI demo"]) == 0
    project = json.loads(capsys.readouterr().out)
    assert project["projectName"] == "CLI demo"
    assert project["files"][0]["fileContent"] == content.decode()


def test_cli_module_entry_point(tmp_path):
    path = tmp_path / "demo.py"
    path.write_bytes(b"# runnable demo\n")
    result = subprocess.run(
        [sys.executable, "-m", "flowbridge", "file", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["files"][0]["fileContent"] == "# runnable demo\n"


def test_cli_errors_are_json_and_nonzero(tmp_path, capsys):
    assert main(["file", str(tmp_path / "missing.py")]) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "INVALID_INPUT"
    assert "missing.py" not in error["error"]["message"]
