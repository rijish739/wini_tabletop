"""Smart sync: compare md5sums local cloud_run_service/ <-> Pi cloud-CLI/, push only changed files.

Usage:
    $env:PI_PASS="roavai"; python tools/sync_to_pi.py [--dry-run]
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys
import time
from pathlib import Path

import paramiko

# ── connection ────────────────────────────────────────────────────────────────
HOST = os.getenv("PI_HOST", "192.168.0.104")
USER = os.getenv("PI_USER", "winipi5")
PASS = os.getenv("PI_PASS")
REMOTE_REPO = "/home/winipi5/cloud_tutor/cloud-CLI"

# ── what to sync ──────────────────────────────────────────────────────────────
# (local relative to cloud_run_service/, remote relative to REMOTE_REPO/)
LOCAL_ROOT = Path(__file__).resolve().parent.parent / "cloud_run_service"

# Flat Python files at root level
ROOT_FILES = [
    "wini_server.py",
    "tutor_loop.py",
    "learner_state.py",
    "llm_vertex.py",
    "query.py",
    "rag_core.py",
    "session_modes.py",
    "state_backend.py",
    "math_grade.py",
    "mathtext.py",
    "debug_logger.py",
    "board_buddy_renderer.py",
]

# JSON/text files
ROOT_DATA = [
    "persona.json",
]

# Subdirectory packages (sync all .py files in each)
PACKAGES = [
    "voice",
    "response_layer",
    "perception",
    "pacing",
    "cognitive_analyzer",
    "cognitive_classifier",
    "concept_resolver",
    "hope_detector",
    "policy_shadow",
    "board_buddy",
]

DRY_RUN = "--dry-run" in sys.argv


def _md5(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def connect(retries: int = 3):
    if not PASS:
        sys.exit("PI_PASS is not set — run: $env:PI_PASS='roavai'")
    last = None
    for _ in range(retries):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username=USER, password=PASS, timeout=20)
            return c
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1)
    raise last


def remote_md5s(client: paramiko.SSHClient, paths: list[str]) -> dict[str, str]:
    """Return {remote_path: md5} for files that exist on the Pi.
    Splits into batches of 50 to avoid command-line length limits."""
    result = {}
    batch_size = 50
    for i in range(0, len(paths), batch_size):
        batch = paths[i:i + batch_size]
        joined = " ".join(f'"{p}"' for p in batch)
        cmd = f"md5sum {joined} 2>/dev/null"
        _, stdout, _ = client.exec_command(cmd, timeout=120)
        out = stdout.read().decode("utf-8", "replace")
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                result[parts[1].strip()] = parts[0]
    return result


def push_file(client: paramiko.SSHClient, local: Path, remote: str) -> int:
    """Push one file via stdin pipe → base64 -d on the Pi.

    Sending the blob as a command-line arg (printf %s 'blob') breaks for files
    > ~60 KB because the SSH channel's argument limit kicks in and the remote
    host resets the connection. Sending via stdin avoids any arg-length limit.
    """
    data = local.read_bytes()
    blob = base64.b64encode(data)          # bytes, ASCII-safe

    # Prepare the remote dir and open a 'base64 -d > remote' exec channel
    mkdir_cmd = f"mkdir -p $(dirname {remote})"
    _, stdout, _ = client.exec_command(mkdir_cmd, timeout=30)
    stdout.channel.recv_exit_status()

    write_cmd = f"base64 -d > {remote}"
    stdin, stdout, stderr = client.exec_command(write_cmd, timeout=300)
    try:
        # Write the base64 in chunks so SSH doesn't block on a giant single write
        chunk = 65536
        for i in range(0, len(blob), chunk):
            stdin.write(blob[i:i + chunk])
        stdin.channel.shutdown_write()
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR stdin write {remote}: {e}")
        return -1

    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        err = stderr.read().decode()[:200]
        print(f"  ERROR push {remote}: rc={rc} {err}")
        return -1
    return len(data)


def collect_pairs() -> list[tuple[Path, str]]:
    """Collect (local_path, remote_path) for every file we want to sync."""
    pairs: list[tuple[Path, str]] = []

    for name in ROOT_FILES + ROOT_DATA:
        local = LOCAL_ROOT / name
        if local.exists():
            pairs.append((local, f"{REMOTE_REPO}/{name}"))
        else:
            print(f"  [skip] {name} not found locally")

    for pkg in PACKAGES:
        pkg_dir = LOCAL_ROOT / pkg
        if not pkg_dir.is_dir():
            print(f"  [skip] {pkg}/ not found locally")
            continue
        for f in sorted(pkg_dir.rglob("*.py")):
            if "__pycache__" in str(f):
                continue
            rel = f.relative_to(LOCAL_ROOT)
            pairs.append((f, f"{REMOTE_REPO}/{rel.as_posix()}"))
        for f in sorted(pkg_dir.rglob("*.json")):
            rel = f.relative_to(LOCAL_ROOT)
            pairs.append((f, f"{REMOTE_REPO}/{rel.as_posix()}"))

    return pairs


def main():
    pairs = collect_pairs()
    print(f"\n[sync] {len(pairs)} files to check  (local cloud_run_service/ -> Pi {HOST})")

    if not PASS:
        sys.exit("\nSet PI_PASS first:  $env:PI_PASS='roavai'")

    print("[sync] connecting …")
    client = connect()
    try:
        # Batch md5sum query on Pi
        remote_paths = [r for _, r in pairs]
        print(f"[sync] querying {len(remote_paths)} remote md5sums …")
        pi_md5 = remote_md5s(client, remote_paths)

        to_push: list[tuple[Path, str]] = []
        for local, remote in pairs:
            local_hash = _md5(local)
            pi_hash = pi_md5.get(remote, "")
            if local_hash != pi_hash:
                status = "MISSING" if not pi_hash else "CHANGED"
                print(f"  [{status}] {remote}")
                to_push.append((local, remote))

        unchanged = len(pairs) - len(to_push)
        print(f"\n[sync] {len(to_push)} file(s) to push, {unchanged} already match.")

        if not to_push:
            print("[sync] Pi is already up to date — nothing to do.")
            return

        if DRY_RUN:
            print("[sync] --dry-run: NOT pushing.")
            return

        pushed = 0
        failed = 0
        for local, remote in to_push:
            # Reconnect on each file — the Pi's SSH server sometimes drops a
            # channel after a large write. Reconnecting is cheap (<1 s).
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
            client = connect()
            size = push_file(client, local, remote)
            if size >= 0:
                print(f"  [ok] {remote.split('cloud-CLI/')[-1]}  ({size} bytes)")
                pushed += 1
            else:
                failed += 1

        print(f"\n[sync] done: {pushed} pushed, {failed} failed, {unchanged} unchanged.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
