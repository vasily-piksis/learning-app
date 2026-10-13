"""Update code while keeping host configuration and the persistent Docker volume."""

import argparse
import fcntl
import ipaddress
import json
import os
import shutil

# This operator tool launches fixed Docker/Git commands, without shell or HTTP input.
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def capture(command, **kwargs):
    command = [shutil.which(command[0]) or command[0], *command[1:]]
    # Internal Docker/Git command lists; no shell and no request-controlled arguments.
    return subprocess.run(  # nosec B603
        command,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    ).stdout.strip()


def run(command, **kwargs):
    command = [shutil.which(command[0]) or command[0], *command[1:]]
    subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, check=True, **kwargs)  # nosec B603


def private_backups():
    path = ROOT / "backups"
    path.mkdir(exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def runtime_environment(config):
    environment = os.environ.copy()
    network = config["services"]["app"].get("labels", {}).get("traefik.docker.network")
    if network:
        proxy = environment.get("TRAEFIK_CONTAINER", "traefik")
        networks = json.loads(
            capture(
                [
                    "docker",
                    "inspect",
                    proxy,
                    "--format",
                    "{{json .NetworkSettings.Networks}}",
                ]
            )
        )
        address = networks[network]["IPAddress"]
        ipaddress.ip_address(address)
        # Compose takes this override from the process environment. .env is never rewritten.
        environment["FORWARDED_ALLOW_IPS"] = address
    return environment


def start():
    config = json.loads(capture(["docker", "compose", "config", "--format", "json"]))
    environment = runtime_environment(config)
    image = config["services"]["app"].get("image", config["name"] + "-app")
    identifier = capture(["docker", "compose", "ps", "-q", "app"])
    previous = None
    if identifier:
        previous = capture(["docker", "inspect", identifier, "--format", "{{.Image}}"])
    run(["docker", "compose", "build", "app"], env=environment)
    # Verify import/startup as the non-root app user without exposing family data or credentials.
    capture(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--label",
            "traefik.enable=false",
            "--entrypoint",
            "python",
            image,
            "-c",
            "from app.main import production_app; production_app()",
        ]
    )
    try:
        run(["docker", "compose", "up", "-d", "--no-build", "--wait"], env=environment)
    except subprocess.CalledProcessError:
        if previous:
            rollback = private_backups() / "rollback.json"
            rollback.write_text(json.dumps({"services": {"app": {"image": previous}}}))
            rollback.chmod(0o600)
            files = ["-f", "compose.yaml"]
            if (ROOT / "compose.override.yaml").exists():
                files += ["-f", "compose.override.yaml"]
            run(
                [
                    "docker",
                    "compose",
                    *files,
                    "-f",
                    str(rollback),
                    "up",
                    "-d",
                    "--no-build",
                    "--wait",
                ],
                env=environment,
            )
            print("Previous image restarted; the persistent data volume was retained", flush=True)
        raise


def update():
    backups = private_backups()
    with (backups / ".update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another update is already running") from error
        if capture(["git", "status", "--porcelain"]):
            raise RuntimeError("Local source changes: update stopped")
        protected = {
            name: (ROOT / name).read_bytes()
            for name in (".env", "compose.override.yaml")
            if (ROOT / name).exists()
        }
        modes = {name: (ROOT / name).stat().st_mode & 0o777 for name in protected}
        if capture(["git", "ls-files", "--", ".env", "compose.override.yaml"]):
            raise RuntimeError("Private server configuration must not be tracked in Git")
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        for name, contents in protected.items():
            prefix = "env-" if name == ".env" else "compose-override-"
            path = backups / (prefix + stamp + ".bak")
            # Create with private permissions before writing secret values.
            with open(path, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)) as saved:
                saved.write(contents)
        print("Backing up the current server database and uploaded files", flush=True)
        run(["sh", "scripts/backup.sh", str(backups)])
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        run(["git", "pull", "--ff-only"], env=environment, umask=0o022)
        changed = [
            name
            for name, contents in protected.items()
            if not (ROOT / name).exists() or (ROOT / name).read_bytes() != contents
        ]
        for name in changed:
            path = ROOT / name
            path.touch(mode=modes[name], exist_ok=True)
            path.chmod(modes[name])
            path.write_bytes(protected[name])
        if changed:
            raise RuntimeError("Server configuration was restored; update stopped")
        # The Python updater has already been loaded into memory. Execute the newly
        # pulled starter instead of continuing to read an overwritten shell script.
        run(["sh", "start.sh"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "update"))
    args = parser.parse_args()
    try:
        {"start": start, "update": update}[args.action]()
    except (RuntimeError, subprocess.CalledProcessError, KeyError) as error:
        raise SystemExit(str(error)) from error
