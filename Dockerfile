# Part 15 Phase A — the Wini brain as a single Cloud Run container.
# The image is `wini_server.py` + its in-process pipeline (perception → retrieval →
# state → generation → T9) with the MiniLM retrieval/HOPE model baked in. The three
# genuinely-remote calls (Vertex Gemini, Cloud STT, Cloud TTS) go out over the
# network from here. Learner state persists to Firestore (Phase E).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    GEN_BACKEND=gemini

# faiss + torch (and their BLAS) need libgomp at runtime; wheels supply the rest.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps in two steps: CPU-only torch from the pytorch index first (so the
# multi-GB CUDA build is never pulled), then everything else. sentence-transformers
# then sees torch already satisfied.
COPY requirements-cloud.txt .
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-cloud.txt

# Bake the retrieval/HOPE embedder so a cold instance never blocks a child's first
# turn on a HuggingFace download (and so the service needs no HF egress at runtime).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Brain code + data (rag_store, models, dataset) — device/UI/tooling excluded via
# .dockerignore.
COPY . .

# Cloud Run injects $PORT; wini_server.main() reads it (falls back to 8123 locally).
CMD ["python", "-u", "wini_server.py"]
