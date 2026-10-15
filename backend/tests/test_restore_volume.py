"""Private, staged restore behavior without an actual Docker daemon."""

import importlib.util
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/restore_volume.py"


def load_restore():
    spec = importlib.util.spec_from_file_location("restore_volume", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backup_bytes():
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w:gz") as archive:
        for name, data in [
            ("learning.sqlite3", b"saved database"),
            ("answer-audio/private.wav", os.urandom(8192)),
        ]:
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), 0o600
            archive.addfile(member, io.BytesIO(data))
    return target.getvalue()


def test_restore_cli_reads_actual_pipe_into_private_temporary_file(tmp_path):
    destination = tmp_path / "data"
    destination.mkdir()
    (destination / "stale").write_bytes(b"old")
    bootstrap = f"""
import importlib.util,os,stat,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('restore_volume',{str(SCRIPT)!r})
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
destination=Path({str(destination)!r})
m.Path=lambda value: destination if value=='/data' else Path(value)
m.tempfile.tempdir=str(destination.parent)
real=m.tempfile.NamedTemporaryFile
files=[]
def private_file(*args,**kwargs):
 f=real(*args,**kwargs)
 assert stat.S_IMODE(os.fstat(f.fileno()).st_mode)==0o600
 files.append(f.name)
 return f
m.tempfile.NamedTemporaryFile=private_file
sys.argv=['restore_volume.py','-']
m.main()
assert len(files)==1 and not Path(files[0]).exists()
"""
    subprocess.run([sys.executable, "-c", bootstrap], input=backup_bytes(), check=True, umask=0o022)
    assert (destination / "learning.sqlite3").read_bytes() == b"saved database"
    assert not (destination / "stale").exists()
    assert (destination / "answer-audio/private.wav").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("damage", ["invalid", "half", "footer"])
def test_invalid_or_truncated_backup_never_clears_destination(tmp_path, monkeypatch, damage):
    module = load_restore()
    monkeypatch.setattr(module.tempfile, "tempdir", str(tmp_path.resolve()))
    destination = tmp_path / "data"
    destination.mkdir()
    sentinel = destination / "learning.sqlite3"
    sentinel.write_bytes(b"known-good database")
    contents = backup_bytes()
    contents = (
        b"invalid archive"
        if damage == "invalid"
        else contents[: len(contents) // 2]
        if damage == "half"
        else contents[:-8]
    )
    archive = tmp_path / "backup.tar.gz"
    archive.write_bytes(contents)
    archive.chmod(0o600)
    monkeypatch.setattr(
        module, "Path", lambda value: destination if value == "/data" else Path(value)
    )
    with pytest.raises((tarfile.TarError, EOFError, OSError, ValueError)):
        module.restore(archive, destination)
    assert sentinel.read_bytes() == b"known-good database"
    assert sorted(path.name for path in destination.iterdir()) == ["learning.sqlite3"]
    assert archive.stat().st_mode & 0o777 == 0o600
