"""Remote helper for the winipi5 device: run commands, push files, pull files.

    python tools/pi.py run  "<shell command>"
    python tools/pi.py push <local> <remote> [<local> <remote> ...]
    python tools/pi.py pull <remote> <local> [<remote> <local> ...]

Credentials come from the environment — NOTHING is hardcoded, because this file is
committed and the repo has a GitHub remote:

    PI_HOST   default 192.168.29.24   (see PI_ACCESS.md for why the IP is pinned)
    PI_USER   default winipi5
    PI_PASS   required — no default

See PI_ACCESS.md (untracked, on this machine) for the values and the full connection
guide. Every non-obvious workaround below is load-bearing; the comments say why.
"""
from __future__ import annotations

import base64
import os
import sys
import time

import paramiko

# The Windows console is cp1252 and the Pi prints UTF-8 (tutor answers contain — and
# →). Without this, a run that merely *echoes an answer* dies on an encode error.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — older/!tty streams have no reconfigure
        pass

# winipi5.local resolves only over IPv6 here and mDNS is flaky, so the IPv4 is pinned.
# If the board moves, find it with `arp -a` (Raspberry Pi OUI 2c:cf:67) and set PI_HOST.
HOST = os.getenv("PI_HOST", "192.168.29.24")
USER = os.getenv("PI_USER", "winipi5")
PASS = os.getenv("PI_PASS")
REPO = "/home/winipi5/cloud_tutor/cloud-CLI"


def connect(retries: int = 3):
    if not PASS:
        sys.exit("PI_PASS is not set — see PI_ACCESS.md")
    last = None
    for _ in range(retries):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username=USER, password=PASS, timeout=20)
            return c
        except Exception as e:  # noqa: BLE001 — retry any transport hiccup
            last = e
            time.sleep(1)
    raise last


def run(cmd: str, timeout: int = 900) -> int:
    c = connect()
    try:
        _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
    finally:
        c.close()
    if out:
        print(out, end="")
    if err:
        print("[stderr] " + err, end="")
    print(f"\n[rc={rc}]")
    return rc


def pull(pairs) -> None:
    c = connect()
    try:
        s = c.open_sftp()
        # The FIRST SFTP request on a fresh channel intermittently returns a bogus
        # ENOENT on this board. A throwaway listdir warms the channel; everything
        # after it behaves. Reuse ONE connection for the whole batch.
        for _ in range(3):
            try:
                s.listdir(".")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        for remote, local in pairs:
            for attempt in range(3):
                try:
                    s.get(remote, local)
                    print(f"pull {remote} -> {local}")
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 2:
                        raise
                    print(f"  retry {remote} ({e})")
                    time.sleep(1)
        s.close()
    finally:
        c.close()


def push(pairs) -> None:
    """Upload via base64 over the exec channel.

    SFTP *writes* on this board fail with a bogus ENOENT (both s.put and a raw
    s.open(...,'wb')) while reads and exec are fine — so pushes go through
    `base64 -d`. Source files are tens of KB; the encoding overhead is irrelevant.
    """
    c = connect()
    try:
        for local, remote in pairs:
            with open(local, "rb") as f:
                blob = base64.b64encode(f.read()).decode("ascii")
            cmd = (f"mkdir -p $(dirname {remote}) && "
                   f"printf %s '{blob}' | base64 -d > {remote} && wc -c < {remote}")
            _, stdout, stderr = c.exec_command(cmd, timeout=300)
            out = stdout.read().decode().strip()
            rc = stdout.channel.recv_exit_status()
            if rc != 0:
                raise RuntimeError(f"push {local} failed: "
                                   f"{stderr.read().decode()[:300]}")
            print(f"push {local} -> {remote} ({out} bytes)")
    finally:
        c.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    op = sys.argv[1]
    if op == "run":
        sys.exit(run(" ".join(sys.argv[2:])))
    args = sys.argv[2:]
    pairs = list(zip(args[0::2], args[1::2]))
    if op == "push":
        push(pairs)
    elif op == "pull":
        pull(pairs)
    else:
        sys.exit(__doc__)
