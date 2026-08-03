# Wini Cloud Cost Optimization — Report & Strategy

**Date:** 2026-07-25 · **Scope:** the Part 15 cloud deployment (`wini-brain` on Cloud Run,
asia-south1, + Vertex Gemini / Cloud STT / Cloud TTS / Firestore).
**Goal:** cut cost **without any loss of performance or quality.** First-principles analysis,
current prices (researched July 2026), tiered strategy, verification gates.

---

## 1. Executive summary

At today's single-device volume, **~99% of the bill is one thing: an always-powered warm
brain instance (~$227/month).** Per-turn usage (Gemini/STT/TTS) is nearly free — the STT and
TTS free tiers absorb it.

The central finding is a **billing-model mismatch**, not a resource-size problem:

> We are paying to keep **4 CPUs powered 24/7**, but the brain only *uses* CPU for **~4
> seconds per turn**. Between turns it needs to stay **in memory**, not stay **powered**.
> We are on Cloud Run's *instance-based* (`--no-cpu-throttling`) billing — which bills idle
> CPU continuously — **only** because the brain's 70-second load runs on a background thread.
> Cloud Run's **startup-probe pattern feeds that load during startup instead**, which unlocks
> *request-based* billing: **idle instances are billed for memory only, CPU only during
> turns.** Same warm behaviour, ~1/4 the cost, zero quality/performance change.

**Headline result of the strategy:**

| Stage | Monthly (1 device) | vs now | Quality/perf impact |
|---|---|---|---|
| **Now** (instance-based, 4 vCPU / 8 GiB, min=1) | **~$227** | — | — |
| **Tier 1** — request-based + startup probe | **~$53** | −77% | **none** |
| **Tier 2** — + drop PyTorch (ONNX MiniLM) + right-size to 2 vCPU / 4 GiB | **~$27** | −88% | none (gated) |
| **Tier 3** — + 1-yr request-based CUD (17%) | **~$22** | −90% | none |

Every step is a config/flag change and **independently reversible**, in the Part 13/15
discipline.

---

## 2. First-principles cost decomposition — where every dollar goes, and *why*

Cost = **Fixed (warm brain)** + **Variable (per turn) × volume**.

### 2.1 Fixed: the warm instance (the whole game at low volume)
Instance-based billing (Tier-1 asia-south1 rates: $0.000018/vCPU-s, $0.000002/GiB-s), one
instance alive 24/7 (2,628,000 s/mo):

| | calc | $/mo |
|---|---|---|
| vCPU (4) | 10,512,000 s − 180k free × $0.000018 | **$186** |
| Memory (8 GiB) | 21,024,000 s − 360k free × $0.000002 | **$41** |
| **Fixed total** | | **~$227** |

**Why it's this shape:** `min-instances=1` (never cold-start a child) × `--no-cpu-throttling`
(the 70 s `TutorLoop` load runs on a background thread and needs CPU *outside* request
handling) × 4 vCPU / 8 GiB (sized for PyTorch + MiniLM + FAISS).

### 2.2 Variable: per turn (~$0.012), mostly absorbed by free tiers
Gemini 2.5-flash ~$0.0022 (perception+generation) · Cloud STT ~$0.0020 (free: 60 min/mo) ·
Cloud TTS Chirp3-HD ~$0.0075 (free: **1M chars/mo** ≈ 4,000 turns) · Firestore+egress ~$0.

**At one device this is essentially free.** It only becomes material at fleet scale (§5).

### 2.3 The three cost drivers, ranked by first-principles attackability
1. **Idle CPU we don't use** — the $186/mo. *Root cause: billing model, forced by background
   load.* → **Tier 1** (biggest, zero-impact).
2. **Over-provisioned memory/CPU** — 8 GiB is sized for PyTorch, which we don't need at
   runtime. → **Tier 2**.
3. **Uptime we may not need** — 24/7 warm even when no child is awake. → **Tier 4** (optional).

---

## 3. The core insight, stated precisely

The workload is: **long-lived resident state (MiniLM/FAISS/graph in RAM) + short bursts of
compute (a ~4 s turn)**. The right Cloud Run shape for that is:

- **Keep the instance resident** (`min-instances=1`) so state stays warm → no cold start.
- **Bill CPU only during the bursts** (request-based) → stop paying for 24 h of idle CPU.
- **Feed the one-time load during startup** (startup probe) → the reason we're stuck on the
  expensive mode disappears.

We are currently paying the *instance-based* premium purely as a workaround for the background
load. Remove that workaround and the premium goes away — with **no change to how warm the
service is** (it stays loaded in memory between turns; only *idle CPU* is no longer billed).

---

## 4. The strategy (tiered by risk/effort; all reversible)

### Tier 1 — Switch to request-based billing + a readiness startup probe · **−77%, zero impact**
**What:** (a) `/health` returns **503 until `ready`** (small code change); (b) add a Cloud Run
**startup probe** on `/health` with a `failureThreshold × periodSeconds` window ≥ load time
(~90 s) and keep **startup-CPU-boost**; (c) **remove `--no-cpu-throttling`** (→ request-based).

**Why it works:** during the startup phase Cloud Run allocates CPU (boosted) until the startup
probe passes — so the 70 s background load completes *before* the instance is marked ready.
After that the min-instance sits **idle, billed for memory only** (docs: "idle minimum
instances are billed for memory only, not CPU"); each turn allocates CPU just for its ~4 s.

**Cost:** 8 GiB idle × 2,628,000 s × $0.0000025 = **~$53/mo**, + negligible per-turn CPU.

**Quality/perf:** **none.** The instance stays warm in memory → turns are as fast as today.
The child still never hits a cold start.
**Verify:** `/health` reaches `ready` within the probe window on a fresh revision; measure
TTFA on 10 turns before/after — must match. **Rollback:** re-add `--no-cpu-throttling` (one
flag).

### Tier 2 — Drop PyTorch (MiniLM → ONNX Runtime) + right-size to 2 vCPU / 4 GiB · **−88% total**
**What:** run `all-MiniLM-L6-v2` via **ONNX Runtime / Optimum** (no PyTorch at runtime — it's a
documented, supported path; the same runtime we just used for the Silero VAD). Then the
container no longer needs multi-GB torch, so **image ~2.5 GB → ~1 GB**, **resident RAM drops
well under 4 GiB**, boot is faster, and we can **right-size to 2 vCPU / 4 GiB**.

**Cost:** 4 GiB idle × 2,628,000 s × $0.0000025 = **~$26/mo**. Also: faster boot shrinks the
Tier-1 startup window and makes Tier 4 viable; smaller image = less Artifact Registry + faster
deploys.

**Quality/perf:** none **if gated** — this is the one change that *could* shift quality, because
retrieval ranks on MiniLM embeddings. **Hard gate:** ONNX embeddings must match PyTorch
(cosine ≥ 0.999 on a sample of utterances/chunks) before promotion — same discipline as the
STT/generation parity gates. Skip int8 quantization initially (it perturbs embeddings); adopt
only if it passes the same parity gate. Load-test boot + turn latency at 2 vCPU / 4 GiB.
**Rollback:** env flag back to the torch embedder; redeploy prior image.

### Tier 3 — 1-year request-based Committed Use Discount (17%) · **−90% total, zero impact**
Once Tier 1/2 config is stable, buy a **flexible CUD** on the (now small) Cloud Run spend:
request-based CUD is **17%** (1- or 3-yr). ~$27 → **~$22/mo**. Pure billing; no technical
change. *(Note the asymmetry: instance-based CUD is a bigger 28%/46%, but 28% off $227 = $164 —
still ~3× more than request-based at $22. Request-based wins decisively despite the smaller
discount; don't be lured by the larger headline percentage.)*

### Tier 4 — Scheduled scale-to-zero in off-hours · optional, **situational**
If usage is time-boxed (e.g. a child uses it a few hours/day), a Cloud Scheduler job can set
`min-instances=1` only during the active window and `0` overnight/school-hours. Cuts the idle
memory further (~50–65%). **Trade:** an off-window session eats a cold start (short after
Tier 2's faster boot, but non-zero) — so this is the one lever with a *mild* UX cost. Present
it as opt-in, not default.

### Variable-cost hygiene (irrelevant at 1 device; important at fleet scale)
- **TTS phrase cache** — fillers, canned/farewell lines, and repeated questions are re-
  synthesized every time today. Cache PCM by text hash (the server already caches filler PCM).
  Zero quality impact; meaningful once past the 1M-char free tier.
- **Prompt-token trim** — the generation prompt (manifest + history) is the input-token driver.
  Trim redundant context / cap history length. Keep perception's **context cache** hit-rate
  high (memoize by normalized text — already done) so the 6,062-token block bills at cache
  rate. No quality impact if done against the eval gates.
- **Do not** switch generation to Flash-Lite for cost — you measured it *slower* off-region
  (Part 15 Phase C); that's a latency regression, excluded by the no-perf-impact rule.

---

## 5. Projected cost curve

**Single device** (the current reality):

| | Cloud Run | STT | TTS | Gemini | **Total/mo** |
|---|---|---|---|---|---|
| Now | $227 | ~$0 | ~$0 | ~$1–11 | **~$228–238** |
| Tier 1 | $53 | ~$0 | ~$0 | ~$1–11 | **~$54–64** |
| Tier 1+2 | $27 | ~$0 | ~$0 | ~$1–11 | **~$28–38** |
| Tier 1+2+3 | $22 | ~$0 | ~$0 | ~$1–11 | **~$23–33** |

**10 devices, active** (~30k turns/mo) — the *fixed* brain cost amortizes across the fleet; the
variable costs (esp. TTS) dominate:

| | Cloud Run | STT | TTS (w/ phrase cache) | Gemini | **Total/mo** |
|---|---|---|---|---|---|
| Now | ~$300–500¹ | ~$57 | ~$240 → ~$120² | ~$75 | **~$550–750** |
| Optimized | ~$60–120¹ | ~$57 | ~$120² | ~$60³ | **~$300–360** |

¹ scales with *peak concurrency*, not total turns (raise `max-instances`; request-based means
idle burst-instances cost ~nothing). ² phrase-caching common lines roughly halves TTS at scale.
³ prompt trimming + high cache-hit perception.

**Key structural point:** the warm-brain cost is a **shared fixed cost** — it does *not*
multiply per device. So the per-device economics *improve* as you add devices; the fleet
drivers become TTS then Gemini, both attackable without quality loss (phrase cache, prompt
trim).

---

## 6. What NOT to do (and why) — rejected levers

| Lever | Why rejected |
|---|---|
| **Gemini → Flash-Lite** | Measured **slower** off-region (Phase C) → latency regression. |
| **Cheaper TTS voice (Standard/Neural2)** | Direct **quality** loss (the natural Chirp3-HD voice is the product's feel). |
| **Vertex Provisioned Throughput** | *More* expensive at low volume; it buys latency-variance control at high volume, not savings. |
| **Split the monolith into functions** | Adds network hops between latency-coupled components → **slower** (the Part 15 thesis). |
| **GPU instance** | No GPU workload; pure added cost. |
| **int8-quantized embeddings (unguarded)** | Perturbs embeddings → could shift retrieval ranking = quality risk. Only with a parity gate. |

---

## 7. Implementation sequencing

1. **Tier 1** first — biggest win, smallest change, zero quality risk. (a) `/health` → 503
   until ready; (b) redeploy with a startup probe + request-based billing; (c) verify readiness
   timing + TTFA parity. **~$227 → ~$53.**
2. **Tier 2** — export MiniLM to ONNX, add an embedder flag, **pass the embedding-parity gate**,
   right-size to 2 vCPU / 4 GiB, load-test. **→ ~$27.**
3. **Tier 3** — once the config has run stable for a week or two, buy the 1-yr request-based
   CUD. **→ ~$22.**
4. **Variable hygiene** — implement before/at fleet growth: TTS phrase cache, prompt trim.
5. **Tier 4** — only if usage is genuinely time-boxed and the (post-Tier-2) cold start is
   acceptable off-window.

---

## 8. Verification gates (no-regression discipline)

- **Tier 1:** fresh revision reaches `/health ready` inside the startup-probe window; TTFA on
  10 live turns within the current envelope; no `ready:false` 503s served to a real turn.
- **Tier 2:** ONNX-vs-torch embedding **cosine ≥ 0.999** on a sample (hard gate — protects
  retrieval quality); boot time + turn latency at 2 vCPU / 4 GiB within budget; the perception
  and behavioral eval gates still pass (they consume MiniLM via the resolver cross-check).
- **Tier 3:** billing only — none.
- Everything reversible by one flag/config, per the Part 13/15 rollback discipline.

---

## 9. Bottom line

The single highest-leverage move is **Tier 1** — it alone cuts the bill **~77% with no code-
path change to the pipeline and no quality or latency impact**, because we are simply no longer
paying for idle CPU the workload never uses. Tiers 2–3 take it to **~90% off (~$22/mo)**. The
per-turn costs are already near-free at one device and only matter at fleet scale, where they
amortize the (now-small) fixed cost and are themselves attackable (phrase cache, prompt trim)
without touching quality.

**Recommended immediate action: implement Tier 1.**

---

### Sources (researched July 2026)
- Cloud Run pricing & billing model — https://cloud.google.com/run/pricing ·
  https://docs.cloud.google.com/run/docs/configuring/billing-settings
- Request- vs instance-based idle billing ("idle min-instances billed for memory only") —
  https://cloudwebschool.com/docs/gcp/cost-management/cloud-run-cost-optimisation/
- Startup CPU boost + startup probes for slow init —
  https://cloud.google.com/blog/products/serverless/announcing-startup-cpu-boost-for-cloud-run--cloud-functions
- Cloud Run committed use discounts (17% request-based) — https://docs.cloud.google.com/run/cud
- MiniLM on ONNX Runtime without PyTorch (Optimum) —
  https://huggingface.co/philschmid/all-MiniLM-L6-v2-optimum-embeddings
- Vertex Gemini / STT / TTS pricing — https://cloud.google.com/vertex-ai/pricing ·
  https://cloud.google.com/speech-to-text/pricing · https://cloud.google.com/text-to-speech/pricing
