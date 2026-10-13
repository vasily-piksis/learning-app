"""Exercise real Git updates and protected files; Docker is tested at deployment."""

import importlib.util
import subprocess
import tarfile
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2]


def load_deploy():
    spec = importlib.util.spec_from_file_location("learning_deploy", SOURCE / "scripts/deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()


def repository(tmp_path):
    upstream, root = tmp_path / "upstream", tmp_path / "server"
    upstream.mkdir()
    git(upstream, "init", "-b", "main")
    git(upstream, "config", "user.email", "tests@example.invalid")
    git(upstream, "config", "user.name", "Deployment tests")
    (upstream / ".gitignore").write_text(
        ".env\ncompose.override.yaml\nbackups/\ndata/\nrestarted\n"
    )
    (upstream / "start.sh").write_text("#!/bin/sh\nset -eu\necho old > restarted\n")
    (upstream / "start.sh").chmod(0o755)
    scripts = upstream / "scripts"
    scripts.mkdir()
    # Only the external Docker backup boundary is substituted. The archive is real.
    (scripts / "backup.sh").write_text(
        '#!/bin/sh\nset -eu\n[ "${TEST_BACKUP_FAILURE:-0}" != 1 ] || exit 2\nmkdir -p "$1"\ntar -czf "$1/volume.tar.gz" -C data .\n'
    )
    (scripts / "backup.sh").chmod(0o755)
    git(upstream, "add", ".")
    git(upstream, "commit", "-m", "Initial server version")
    subprocess.run(["git", "clone", str(upstream), str(root)], check=True, capture_output=True)
    (root / ".env").write_bytes(b"APP_ORIGIN=https://study.example.invalid\nTEST_SECRET=keep-me\n")
    (root / ".env").chmod(0o600)
    (root / "compose.override.yaml").write_text("services: {}\n")
    (root / "data").mkdir()
    (root / "data/photo.jpg").write_bytes(b"private uploaded file")
    (upstream / "start.sh").write_text("#!/bin/sh\nset -eu\necho new > restarted\n")
    git(upstream, "add", "start.sh")
    git(upstream, "commit", "-m", "New application version")
    return root, upstream


def test_update_uses_new_start_script_and_preserves_env_config_and_files(tmp_path):
    module = load_deploy()
    root, upstream = repository(tmp_path)
    module.ROOT = root
    protected = {
        path: (root / path).read_bytes()
        for path in (".env", "compose.override.yaml", "data/photo.jpg")
    }
    module.update()
    assert git(root, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")
    assert (root / "restarted").read_text().strip() == "new"
    assert {path: (root / path).read_bytes() for path in protected} == protected
    assert (root / ".env").stat().st_mode & 0o777 == 0o600
    env_backups = list((root / "backups").glob("env-*.bak"))
    assert len(env_backups) == 1 and env_backups[0].read_bytes() == protected[".env"]
    assert env_backups[0].stat().st_mode & 0o777 == 0o600
    with tarfile.open(root / "backups/volume.tar.gz") as archive:
        assert archive.extractfile("./photo.jpg").read() == protected["data/photo.jpg"]
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("failure", ["dirty", "backup"])
def test_unsafe_update_stops_before_git_pull_and_restart(tmp_path, failure, monkeypatch):
    module = load_deploy()
    root, _ = repository(tmp_path)
    module.ROOT = root
    before = git(root, "rev-parse", "HEAD")
    if failure == "dirty":
        (root / "start.sh").write_text("local edits\n")
    else:
        # The backup fails while the source remains a clean fast-forward checkout.
        monkeypatch.setenv("TEST_BACKUP_FAILURE", "1")
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        module.update()
    assert git(root, "rev-parse", "HEAD") == before
    assert not (root / "restarted").exists()


def test_runtime_environment_refreshes_proxy_without_rewriting_env(tmp_path, monkeypatch):
    module = load_deploy()
    (tmp_path / ".env").write_text("FORWARDED_ALLOW_IPS=old\nPRIVATE_KEY=keep\n")
    before = (tmp_path / ".env").read_bytes()
    monkeypatch.setenv("TRAEFIK_CONTAINER", "my-proxy")

    def run(command, **kwargs):
        assert command == [
            "docker",
            "inspect",
            "my-proxy",
            "--format",
            "{{json .NetworkSettings.Networks}}",
        ]
        return '{"private-network":{"IPAddress":"172.27.0.3"}}'

    monkeypatch.setattr(module, "capture", run)
    result = module.runtime_environment(
        {"services": {"app": {"labels": {"traefik.docker.network": "private-network"}}}}
    )
    assert result["FORWARDED_ALLOW_IPS"] == "172.27.0.3"
    assert (tmp_path / ".env").read_bytes() == before


def test_unexpected_config_changes_are_all_restored_before_restart(tmp_path):
    module = load_deploy()
    root, upstream = repository(tmp_path)
    module.ROOT = root
    before = {name: (root / name).read_bytes() for name in (".env", "compose.override.yaml")}
    (upstream / ".env").write_text("DEFAULT_ONLY=yes\n")
    (upstream / "compose.override.yaml").write_text("services: {app: {image: wrong}}\n")
    git(upstream, "add", "-f", ".env", "compose.override.yaml")
    git(upstream, "commit", "-m", "Accidental tracked server defaults")
    with pytest.raises(RuntimeError, match="configuration was restored"):
        module.update()
    assert {name: (root / name).read_bytes() for name in before} == before
    assert not (root / "restarted").exists()
    backups = list((root / "backups").glob("compose-override-*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == before["compose.override.yaml"]


def test_plain_docker_installation_does_not_require_traefik(monkeypatch):
    module = load_deploy()
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    assert (
        module.runtime_environment({"services": {"app": {}}})["FORWARDED_ALLOW_IPS"] == "127.0.0.1"
    )
