"""Shared Vertex AI Gemini client for text generation.

Part 11 Stage 0 deliverable (see PART11_GEMINI_PERCEPTION_LAYER.md SS8). Today this
is used only by voice_latency_spike.py to measure the added latency of a cloud
Flash call; tutor_loop.py still generates with local Qwen (PERCEPTION_BACKEND has
not been flipped). Region defaults to asia-south1 per the CLAUDE.md mandate,
independent of voice/config.py's location (STT/TTS models there default to
"global" for a different reason).
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.getenv("VERTEX_GENERATION_MODEL", "gemini-2.5-flash")
DEFAULT_REGION = os.getenv("VERTEX_REGION", "asia-south1")
# Generous enough to survive a cold first call + a large manifest-grounded prompt,
# while still bounding the "stalled for hours" SDK failure mode (CLAUDE.md gotcha).
DEFAULT_TIMEOUT_S = float(os.getenv("VERTEX_GENERATION_TIMEOUT_S", "20"))
# Max gap between two streamed deltas before we call the stream dead (Part 13
# Stage 2). Separate from the overall bound: a stream that produces one token and
# then hangs must abort quickly, not sit until the overall deadline.
STREAM_CHUNK_TIMEOUT_S = float(os.getenv("VERTEX_STREAM_CHUNK_TIMEOUT_S", "10"))

_executor = ThreadPoolExecutor(max_workers=4)
_STREAM_DONE = object()


@dataclass
class FlashResult:
    text: str
    latency_ms: int


@dataclass
class JsonResult:
    data: object            # parsed JSON (dict) or None on parse failure
    text: str               # raw model text (for logging / debugging)
    latency_ms: int
    ok: bool                # True iff structured JSON parsed cleanly


_clients: dict[str, object] = {}
# Guards the memo: the server now warms Gemini generation and perception
# CONCURRENTLY, and an unlocked check-then-set would let both threads pay the
# 4-9 s construction and one of them throw its client away.
_clients_lock = threading.Lock()


def _client(location: str):
    """Memoized per location. The first call pays ADC/channel setup (measured
    ~4-8s cold); every call after that in this process is a plain HTTP round
    trip (measured ~0.9-1.1s). A long-lived service must build this once and
    reuse it -- constructing a fresh client per turn was silently eating the
    entire cold-start cost on every single call."""
    client = _clients.get(location)
    if client is not None:
        return client

    from google import genai

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set. Add it to .env or export it "
            "(gcloud config get-value project can tell you the active one)."
        )
    with _clients_lock:
        client = _clients.get(location)      # re-check: another thread may have won
        if client is None:
            client = genai.Client(vertexai=True, project=project, location=location)
            _clients[location] = client
    return client


def generate_reply(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    location: str = DEFAULT_REGION,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    temperature: float = 0.4,
    max_output_tokens: int = 200,
) -> FlashResult:
    """One Vertex Gemini Flash call, bounded by a hard wall-clock timeout.

    SDK-level HttpOptions timeouts have stalled for hours in this project before
    (CLAUDE.md gotcha) -- never rely on them alone. The ThreadPoolExecutor future
    is what actually bounds the call from the caller's side.
    """
    from google.genai import types

    client = _client(location)

    def _call():
        return client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                system_instruction=system,
                # Gemini 2.5 Flash defaults to spending part of the output-token
                # budget on hidden "thinking" tokens, which can eat the whole
                # budget on a short reply and return empty text (finish_reason
                # MAX_TOKENS, no visible content). Disable it: latency and
                # token cost both matter more than reasoning depth here.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

    t0 = time.perf_counter()
    future = _executor.submit(_call)
    try:
        response = future.result(timeout=timeout_s)
    except _FutureTimeoutError as exc:
        raise TimeoutError(f"Gemini Flash call exceeded {timeout_s}s") from exc
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return FlashResult(text=(getattr(response, "text", "") or "").strip(), latency_ms=latency_ms)


def generate_reply_stream(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    location: str = DEFAULT_REGION,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    chunk_timeout_s: float = STREAM_CHUNK_TIMEOUT_S,
    temperature: float = 0.4,
    max_output_tokens: int = 200,
):
    """Stream one Vertex Gemini Flash reply as text deltas.

    Same prompt, same config, same `thinking_budget=0` as ``generate_reply`` —
    only the transport differs, so the concatenated deltas are the reply the
    non-streaming call would have returned.

    Bounded on BOTH axes (CLAUDE.md gotcha: SDK deadlines have stalled for
    hours). ``chunk_timeout_s`` bounds the gap between deltas and ``timeout_s``
    bounds the whole generation; a stalled stream raises TimeoutError so the
    caller can fall back, rather than hanging the turn forever.
    """
    import queue as _queue

    from google.genai import types

    client = _client(location)
    q: "_queue.Queue[object]" = _queue.Queue(maxsize=256)

    def _worker():
        try:
            stream = client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system_instruction=system,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            for chunk in stream:
                piece = getattr(chunk, "text", None)
                if piece:
                    q.put(piece)
            q.put(_STREAM_DONE)
        except Exception as e:  # noqa: BLE001 — re-raised on the consumer side
            q.put(e)

    threading.Thread(target=_worker, name="gemini-gen-stream", daemon=True).start()

    t0 = time.perf_counter()
    while True:
        remaining = timeout_s - (time.perf_counter() - t0)
        if remaining <= 0:
            raise TimeoutError(f"Gemini streamed generation exceeded {timeout_s}s")
        try:
            item = q.get(timeout=min(chunk_timeout_s, remaining))
        except _queue.Empty:
            raise TimeoutError(
                f"Gemini stream stalled {chunk_timeout_s}s waiting for a delta")
        if item is _STREAM_DONE:
            return
        if isinstance(item, Exception):
            raise item
        yield item


def _extract_json(text: str):
    """Best-effort parse of a JSON object from model text.

    With response_mime_type=application/json + a response_schema the text is
    already a clean JSON object, so json.loads succeeds directly. The regex
    fallback only matters if a future call drops the mime type."""
    import json as _json
    import re as _re

    text = (text or "").strip()
    if not text:
        return None
    try:
        return _json.loads(text)
    except Exception:  # noqa: BLE001
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        if not m:
            return None
        try:
            return _json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None


def generate_json(
    prompt: str,
    *,
    response_schema,
    system: str | None = None,
    cached_content: str | None = None,
    model: str = DEFAULT_MODEL,
    location: str = DEFAULT_REGION,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    temperature: float = 0.0,
    max_output_tokens: int = 512,
) -> JsonResult:
    """One structured Vertex Gemini call returning enum-constrained JSON.

    This is the Part 11 perception seam (PART11_GEMINI_PERCEPTION_LAYER.md §5):
    ``temperature=0``, ``response_mime_type=application/json`` and a
    ``response_schema`` so the model cannot emit an out-of-vocab intent / concept
    / signal. Same hard wall-clock timeout discipline as ``generate_reply`` — the
    ThreadPoolExecutor future bounds the call, never the SDK's own timeout
    (CLAUDE.md gotcha: SDK-level timeouts have stalled for hours).

    ``cached_content`` is an optional Vertex context-cache resource name (Stage 5)
    holding the large static block (taxonomy + signal defs + concept catalog); when
    set, only the tiny dynamic prompt is sent per turn.
    """
    from google.genai import types

    client = _client(location)

    config_kwargs = dict(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
        response_schema=response_schema,
        # Perception replies are short structured JSON; hidden thinking tokens can
        # eat the whole budget and return empty text (CLAUDE.md gotcha G1).
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    if cached_content is not None:
        config_kwargs["cached_content"] = cached_content
    else:
        config_kwargs["system_instruction"] = system

    def _call():
        return client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )

    t0 = time.perf_counter()
    future = _executor.submit(_call)
    try:
        response = future.result(timeout=timeout_s)
    except _FutureTimeoutError as exc:
        raise TimeoutError(f"Gemini JSON call exceeded {timeout_s}s") from exc
    latency_ms = int((time.perf_counter() - t0) * 1000)
    text = (getattr(response, "text", "") or "").strip()
    data = _extract_json(text)
    return JsonResult(data=data, text=text, latency_ms=latency_ms, ok=data is not None)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Smoke-test the Vertex Gemini Flash client")
    ap.add_argument("--prompt", default="Say hello in one short sentence.")
    ap.add_argument("--system", default=None)
    ap.add_argument("--json", action="store_true",
                    help="exercise the structured-JSON seam with a tiny schema")
    args = ap.parse_args()
    if args.json:
        from google.genai import types

        schema = types.Schema(
            type=types.Type.OBJECT,
            properties={"greeting": types.Schema(type=types.Type.STRING)},
            required=["greeting"],
        )
        r = generate_json(args.prompt, response_schema=schema, system=args.system)
        print(f"[{r.latency_ms} ms | ok={r.ok}] {r.data if r.ok else r.text}")
        return
    result = generate_reply(args.prompt, system=args.system)
    print(f"[{result.latency_ms} ms] {result.text}")


if __name__ == "__main__":
    main()
