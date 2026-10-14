"""Restore an operator-created cold backup inside an isolated Docker helper.

Only regular files/directories are accepted; extraction is staged and validated
before replacing /data. The helper runs as the same non-root app user.
"""

import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def restore(archive: Path, destination: Path):
    if destination.resolve() != Path("/data") or destination.is_symlink():
        raise ValueError("Only the mounted /data volume can be restored")
    with tempfile.TemporaryDirectory(prefix="learning-restore-") as temporary:
        stage = Path(temporary)
        permissions = []
        with tarfile.open(archive, "r:gz") as backup:
            for member in backup:
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not (member.isfile() or member.isdir())
                ):
                    raise ValueError("Unsafe backup member")
                target = stage.joinpath(*relative.parts)
                if not target.resolve().is_relative_to(stage):
                    raise ValueError("Backup member escapes staging")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with backup.extractfile(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    if target.stat().st_size != member.size:
                        raise ValueError("Incomplete backup file")
                permissions.append((target, member.mode & 0o777, member.mtime))
        if not (stage / "learning.sqlite3").is_file():
            raise ValueError("Backup has no application database")
        for target, mode, modified in reversed(permissions):
            target.chmod(mode)
            os.utime(target, (modified, modified))
        for child in destination.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in stage.iterdir():
            shutil.move(str(child), destination / child.name)


if __name__ == "__main__":
    restore(Path(sys.argv[1]), Path("/data"))
