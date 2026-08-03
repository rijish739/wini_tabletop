"""Headless UI stand-in — drives a full lesson over the :8160 channel.

Verifies the brain's state machine without the panel, a mic, or hands: it plays
the part of the C UI, printing every command it receives and replying the way an
attentive child would. Two modes let it also check the calm-failure paths:

    --wrong-first   tap a distractor before the right letter (§Stage 3 retry)
    --no-feed       never drag the object, so the activity times out (§Stage 6)

    ALPHABET_NO_MIC=1 .venv/bin/python -m pi_game.drive_lesson --letter A
    ALPHABET_NO_MIC=1 .venv/bin/python -m pi_game.drive_lesson --lang kn --letter a
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 8160


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", default="en", help="en or kn (default: en)")
    ap.add_argument("--letter", default=None,
                    help="lesson id; defaults to the first of the language "
                         "(A for en, a for kn)")
    ap.add_argument("--lessons", type=int, default=1, help="how many to run")
    ap.add_argument("--wrong-first", action="store_true")
    ap.add_argument("--no-feed", action="store_true")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()
    start_letter = args.letter or ("a" if args.lang == "kn" else "A")

    s = socket.create_connection((HOST, PORT), timeout=10)
    s.settimeout(args.timeout)
    send = lambda o: s.sendall((json.dumps(o) + "\n").encode())   # noqa: E731

    t0 = time.monotonic()
    buf = b""
    done = 0
    tapped_wrong: set[str] = set()
    stages_seen: list[str] = []
    pending_letter: str | None = None    # the letter the touch board is asking for

    while done < args.lessons:
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            print("!! timed out waiting for the brain", file=sys.stderr)
            return 1
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            msg = json.loads(line)
            cmd = msg.get("cmd")
            el = time.monotonic() - t0

            if cmd == "status":
                print(f"[{el:6.1f}s] status {msg['value']:9} {msg.get('text','')[:60]}")
                continue

            if cmd == "ready":
                print(f"[{el:6.1f}s] ready; completed so far: {msg.get('completed')}")
                send({"event": "begin", "letter": start_letter, "lang": args.lang})
                continue

            if cmd == "feedback":
                print(f"[{el:6.1f}s] feedback {msg['kind']}")
                # After a wrong tap the board stays up and the brain keeps
                # waiting — it does NOT re-send the stage — so the stand-in has
                # to tap again here or it just sits there until the timeout.
                if msg["kind"] == "touch_retry" and pending_letter:
                    time.sleep(1.2)
                    print(f"           tapping correct letter {pending_letter}")
                    send({"event": "touch", "letter": pending_letter})
                continue

            if cmd != "stage":
                print(f"[{el:6.1f}s] {msg}")
                continue

            stage, letter = msg["stage"], msg["letter"]
            stages_seen.append(stage)
            print(f"[{el:6.1f}s] STAGE {stage:9} {letter} — {msg.get('text','')}")

            pending_letter = letter if stage == "touch" else None

            if stage == "touch":
                choices = [c["letter"] for c in msg["choices"]]
                print(f"           board: {choices}")
                wrong = [c for c in choices if c != letter]
                if args.wrong_first and wrong and letter not in tapped_wrong:
                    tapped_wrong.add(letter)
                    time.sleep(1.0)
                    print(f"           tapping WRONG letter {wrong[0]}")
                    send({"event": "touch", "letter": wrong[0]})
                else:
                    time.sleep(1.2)
                    send({"event": "touch", "letter": letter})

            elif stage == "activity":
                if args.no_feed:
                    print("           (not feeding — letting it time out)")
                else:
                    time.sleep(2.0)
                    send({"event": "fed"})

            elif stage == "complete":
                done += 1
                time.sleep(0.8)
                send({"event": "next" if done < args.lessons else "quit"})

    print(f"\nstages: {' -> '.join(stages_seen)}")
    expected = ["intro", "listen", "touch", "repeat", "assoc", "activity", "complete"]
    per = stages_seen[:len(expected)]
    print("sequence OK" if per == expected else f"!! expected {expected}, got {per}")
    s.close()
    return 0 if per == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
