import io
import stat
import struct
import zipfile
from dataclasses import replace

import pytest

from flowbridge import CodeManager
from flowbridge.config import ImportLimits
from flowbridge.errors import (
    DuplicateFile,
    FileNotFoundInProject,
    ImportLimitExceeded,
    InvalidArchive,
    InvalidInput,
    InvalidSourceEncoding,
    NoProjectLoaded,
    NoPythonFiles,
)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"", ""),
        ("# café\nprint('✓')\n".encode(), "# café\nprint('✓')\n"),
        (b"\xef\xbb\xbf# BOM\r\n", "# BOM\r\n"),
        (b"# coding: latin-1\r\nname = 'caf\xe9'\r\n", "# coding: latin-1\r\nname = 'café'\r\n"),
        (b"if True:\r\n\t# comment  \r\n\tpass\n\n", "if True:\r\n\t# comment  \r\n\tpass\n\n"),
        (b"def invalid(\r\n    !!!", "def invalid(\r\n    !!!"),
    ],
)
def test_single_file_and_zip_share_exact_source_decoding(make_zip, data, expected):
    manager = CodeManager()
    files = manager.loadFile(io.BytesIO(data), fileName=r"C:\fakepath\Example.PY")
    assert isinstance(files, list) and len(files) == 1
    assert files[0].fileName == files[0].filePath == "Example.PY"
    assert files[0].fileContent == expected
    assert manager.getProject().projectName == "Example"
    zipped = make_zip([("folder/Example.PY", data)])
    files = manager.loadZip(io.BytesIO(zipped), fileName="archive.ZIP")
    assert files[0].fileContent == expected
    assert manager.getProject().projectName == "archive"


@pytest.mark.parametrize(
    "data",
    [
        b"# coding: unknown-encoding\n",
        b"\xff\xfe\n",
        b"# hello\n# second\n'\xff'",
        b"\xef\xbb\xbf# coding: latin-1\n",
        b"# coding: utf-8\n\xff",
        b"# coding: base64_codec\n",
        b"# coding: unicode_escape\n'\\ud800'\n",
    ],
)
def test_invalid_source_encoding_is_atomic(make_zip, data):
    manager = CodeManager()
    manager.loadFile(io.BytesIO(b"# original\r\n"), fileName="good.py")
    original = manager.getProject()
    for kind in ("file", "zip"):
        with pytest.raises(InvalidSourceEncoding) as result:
            if kind == "file":
                manager.loadFile(io.BytesIO(data), fileName="bad.py")
            else:
                manager.loadZip(
                    io.BytesIO(make_zip([("a.py", b""), ("bad.py", data)])), fileName="test.zip"
                )
        assert result.value.filePath == "bad.py"
        assert manager.getProject() is original


def test_nested_paths_duplicate_basenames_filtering_and_order(make_zip):
    entries = [
        ("project/tests/main.py", b"# tests\r\n"),
        ("project/app/main.py", b"# app\n"),
        ("project/app/utils/", b""),
        ("project\\app\\.\\utils//helper.PY", b""),
        ("project/notes.txt", b"ignored"),
        ("project/inner.zip", b"not opened"),
    ]
    for component in ImportLimits().excluded_directories:
        entries.append((f"project/{component}/broken.py", b"\xff"))
    manager = CodeManager()
    files = manager.loadZip(
        io.BytesIO(make_zip(entries)), fileName="Project.zip", projectName=" Demo "
    )
    assert [f.filePath for f in files] == [
        "project/app/main.py",
        "project/app/utils/helper.PY",
        "project/tests/main.py",
    ]
    assert [f.fileName for f in files] == ["main.py", "helper.PY", "main.py"]
    assert len({f.fileID for f in files}) == 3
    assert manager.getProject().projectName == "Demo"
    assert manager.getSourceFileByPath(r"project\tests\.\main.py") is files[2]
    assert manager.getSourceFile(files[0].fileID) is files[0]
    with pytest.raises(FileNotFoundInProject):
        manager.getSourceFile("project/app/main.py")


def test_custom_exclusions(make_zip):
    manager = CodeManager(limits=replace(ImportLimits(), excluded_directories=frozenset({"skip"})))
    files = manager.loadZip(
        io.BytesIO(make_zip([("skip/x.py", b"\xff"), ("venv/x.py", b"")])), fileName="x.zip"
    )
    assert [f.filePath for f in files] == ["venv/x.py"]


def test_new_import_replaces_project_and_creates_fresh_ids():
    manager = CodeManager()
    first = manager.loadFile(io.BytesIO(b""), fileName="one.py")
    original = manager.getProject()
    second = manager.loadFile(io.BytesIO(b""), fileName="one.py", projectName="New")
    assert manager.getProject().projectID != original.projectID
    assert first[0].fileID != second[0].fileID
    assert manager.getProject().files == second
    assert manager.getProject().projectName == "New"
    with pytest.raises(FileNotFoundInProject):
        manager.getSourceFile(first[0].fileID)


def test_missing_lookups():
    manager = CodeManager()
    for call in (
        manager.getProject,
        lambda: manager.getSourceFile("x"),
        lambda: manager.getSourceFileByPath("main.py"),
    ):
        with pytest.raises(NoProjectLoaded):
            call()
    manager.loadFile(io.BytesIO(b""), fileName="one.py")
    with pytest.raises(FileNotFoundInProject):
        manager.getSourceFileByPath("missing.py")
    with pytest.raises(InvalidInput):
        manager.getSourceFileByPath("../one.py")


@pytest.mark.parametrize("filename", ["bad.txt", "", "folder/", "nul\x00.py", "C:main.py", ".."])
def test_invalid_upload_names(filename):
    with pytest.raises(InvalidInput):
        CodeManager().loadFile(io.BytesIO(b""), fileName=filename)


@pytest.mark.parametrize("kind", ["file", "zip"])
def test_blank_name_override_is_rejected(kind, make_zip):
    manager = CodeManager()
    with pytest.raises(InvalidInput):
        if kind == "file":
            manager.loadFile(io.BytesIO(b""), fileName="a.py", projectName=" ")
        else:
            manager.loadZip(
                io.BytesIO(make_zip([("a.py", b"")])), fileName="a.zip", projectName=" "
            )


@pytest.mark.parametrize("data", [b"", b"not a zip", b"PK\x03\x04bad"])
def test_corrupt_zip_retains_project(data):
    manager = CodeManager()
    manager.loadFile(io.BytesIO(b""), fileName="good.py")
    project = manager.getProject()
    with pytest.raises(InvalidArchive):
        manager.loadZip(io.BytesIO(data), fileName="bad.zip")
    assert manager.getProject() is project


@pytest.mark.parametrize("entries", [[], [("README.txt", b""), ("venv/main.py", b"\xff")]])
def test_no_eligible_python_files(entries, make_zip):
    with pytest.raises(NoPythonFiles):
        CodeManager().loadZip(io.BytesIO(make_zip(entries)), fileName="empty.zip")


@pytest.mark.parametrize(
    "path",
    [
        "../bad.txt",
        "app/../bad.txt",
        "/absolute.txt",
        "C:/evil.txt",
        "C:evil.txt",
        r"\\server\share\bad.txt",
        r"\root\bad.txt",
        "venv/../../bad.txt",
        "app/C:/bad.txt",
    ],
)
def test_unsafe_paths_checked_even_for_excluded_or_non_python_files(path, make_zip):
    with pytest.raises(InvalidArchive) as result:
        CodeManager().loadZip(
            io.BytesIO(make_zip([("ok.py", b""), (path, b"ignored")])), fileName="unsafe.zip"
        )
    assert result.value.filePath is None


def test_nul_in_zip_original_name_is_rejected(make_zip):
    data = make_zip([("badX.py", b"")]).replace(b"badX.py", b"bad\x00.py")
    with pytest.raises(InvalidArchive):
        CodeManager().loadZip(io.BytesIO(data), fileName="unsafe.zip")


def test_invalid_utf8_archive_filename_is_invalid_archive(make_zip):
    data = bytearray(make_zip([("main.py", b"")]))
    central = data.index(b"PK\x01\x02")
    for start, offset in ((0, 6), (central, 8)):
        flags = struct.unpack_from("<H", data, start + offset)[0]
        struct.pack_into("<H", data, start + offset, flags | 0x800)
    data = bytes(data).replace(b"main.py", b"\xffain.py")
    manager = CodeManager()
    manager.loadFile(io.BytesIO(b"# original"), fileName="good.py")
    original = manager.getProject()
    with pytest.raises(InvalidArchive):
        manager.loadZip(io.BytesIO(data), fileName="invalid-name.zip")
    assert manager.getProject() is original


@pytest.mark.parametrize("second", ["app\\main.py", "app/./main.py", "app//main.py"])
@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_duplicate_normalized_archive_paths(second, make_zip):
    with pytest.raises(DuplicateFile):
        CodeManager().loadZip(
            io.BytesIO(make_zip([("app/main.py", b""), (second, b"")])), fileName="duplicate.zip"
        )


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFDIR])
def test_special_python_entries_are_rejected(mode, make_zip):
    info = zipfile.ZipInfo("unsafe.py")
    info.create_system = 3
    info.external_attr = (mode | 0o777) << 16
    with pytest.raises(InvalidArchive):
        CodeManager().loadZip(io.BytesIO(make_zip([(info, b"target.py")])), fileName="unsafe.zip")


def test_encrypted_python_entry_rejected_but_excluded_entry_not_read(make_zip):
    def encrypted(data):
        data = bytearray(data)
        for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            index = data.index(signature)
            struct.pack_into("<H", data, index + offset, 1)
        return bytes(data)

    with pytest.raises(InvalidArchive):
        CodeManager().loadZip(
            io.BytesIO(encrypted(make_zip([("main.py", b"")]))), fileName="encrypted.zip"
        )
    data = encrypted(make_zip([("venv/encrypted.py", b"\xff"), ("ok.py", b"")]))
    assert CodeManager().loadZip(io.BytesIO(data), fileName="excluded.zip")[0].filePath == "ok.py"


def test_crc_corruption_and_unsupported_compression(make_zip):
    for change in ("crc", "compression"):
        data = bytearray(make_zip([("main.py", b"print('original')\n")]))
        central = data.index(b"PK\x01\x02")
        if change == "crc":
            struct.pack_into("<I", data, central + 16, 0)
        else:
            struct.pack_into("<H", data, central + 10, 99)
            struct.pack_into("<H", data, 8, 99)
        with pytest.raises(InvalidArchive):
            CodeManager().loadZip(io.BytesIO(data), fileName="corrupt.zip")


@pytest.mark.parametrize("limit_name", ["max_file_bytes", "max_source_bytes"])
def test_single_file_byte_boundary_and_one_byte_over(limit_name):
    manager = CodeManager(limits=replace(ImportLimits(), **{limit_name: 4}))
    assert manager.loadFile(io.BytesIO(b"#123"), fileName="ok.py")[0].fileContent == "#123"
    original = manager.getProject()
    with pytest.raises(ImportLimitExceeded):
        manager.loadFile(io.BytesIO(b"#1234"), fileName="large.py")
    assert manager.getProject() is original


@pytest.mark.parametrize(
    ("limit_name", "boundary", "over"),
    [
        ("max_file_bytes", [("a.py", b"1234")], [("a.py", b"12345")]),
        (
            "max_source_bytes",
            [("a.py", b"12"), ("b.py", b"34")],
            [("a.py", b"12"), ("b.py", b"345")],
        ),
        (
            "max_uncompressed_bytes",
            [("a.py", b"12"), ("other.txt", b"34")],
            [("a.py", b"12"), ("other.txt", b"345")],
        ),
    ],
)
def test_archive_size_boundaries(limit_name, boundary, over, make_zip):
    manager = CodeManager(limits=replace(ImportLimits(), **{limit_name: 4}))
    manager.loadZip(io.BytesIO(make_zip(boundary)), fileName="ok.zip")
    original = manager.getProject()
    with pytest.raises(ImportLimitExceeded):
        manager.loadZip(io.BytesIO(make_zip(over)), fileName="large.zip")
    assert manager.getProject() is original


@pytest.mark.parametrize("limit_name", ["max_entries", "max_files"])
def test_archive_count_boundaries(limit_name, make_zip):
    manager = CodeManager(limits=replace(ImportLimits(), **{limit_name: 1}))
    manager.loadZip(io.BytesIO(make_zip([("a.py", b"")])), fileName="ok.zip")
    with pytest.raises(ImportLimitExceeded):
        manager.loadZip(io.BytesIO(make_zip([("a.py", b""), ("b.py", b"")])), fileName="over.zip")


def test_archive_upload_boundaries(make_zip):
    data = make_zip([("a.py", b"")])
    CodeManager(limits=replace(ImportLimits(), max_archive_bytes=len(data))).loadZip(
        io.BytesIO(data), fileName="ok.zip"
    )
    with pytest.raises(ImportLimitExceeded):
        CodeManager(limits=replace(ImportLimits(), max_archive_bytes=len(data) - 1)).loadZip(
            io.BytesIO(data), fileName="over.zip"
        )


def test_reads_are_bounded_and_short_reads_supported():
    class ShortStream(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 5
            return super().read(min(size, 2))

    manager = CodeManager(limits=replace(ImportLimits(), max_file_bytes=4))
    assert manager.loadFile(ShortStream(b"1234"), fileName="ok.py")[0].fileContent == "1234"
    with pytest.raises(ImportLimitExceeded):
        manager.loadFile(ShortStream(b"12345"), fileName="large.py")
    with pytest.raises(InvalidInput):
        manager.loadFile(io.StringIO("text"), fileName="bad.py")


def test_imported_code_is_not_executed(tmp_path):
    marker = tmp_path / "executed.txt"
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\nraise RuntimeError('must not run')"
    result = CodeManager().loadFile(io.BytesIO(source.encode()), fileName="danger.py")
    assert result[0].fileContent == source
    assert not marker.exists()


def test_closed_binary_stream_is_invalid_input():
    stream = io.BytesIO(b"data")
    stream.close()
    with pytest.raises(InvalidInput):
        CodeManager().loadFile(stream, fileName="main.py")
