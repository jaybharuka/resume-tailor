import pytest
from app.core.storage import LocalDiskStorage


def test_save_and_load_roundtrip(tmp_path):
    storage = LocalDiskStorage(root=str(tmp_path))
    path = storage.save("sessions/abc/resume.pdf", b"hello world")
    assert path.endswith("resume.pdf")
    assert storage.load("sessions/abc/resume.pdf") == b"hello world"


def test_delete_removes_file(tmp_path):
    storage = LocalDiskStorage(root=str(tmp_path))
    storage.save("file.txt", b"data")
    storage.delete("file.txt")
    with pytest.raises(FileNotFoundError):
        storage.load("file.txt")


def test_save_rejects_path_traversal(tmp_path):
    storage = LocalDiskStorage(root=str(tmp_path))
    with pytest.raises(ValueError):
        storage.save("../escape.txt", b"data")
