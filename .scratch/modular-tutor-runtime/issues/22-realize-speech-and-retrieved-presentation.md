# 22 — Realize speech and retrieved presentation

**What to build:** The `Presentation` Feature Module speech delivery, audio streaming, display card rendering, and initial `RealizationReceipt` generation.

**Blocked by:** 21 — Extract Response Generation and Model Gateway.

**Status:** resolved

- [x] Implement speech synthesis and progressive audio chunk delivery.
- [x] Implement display card translation for text/question cards.
- [x] Emit truthful `RealizationReceipt` capturing delivered beats and spoken text.
- [x] Verify audio and speech tests across device targets.

## Resolution

- Implemented speech and display realization in `cloud_run_service/response_layer/` and integrated receipts into turn coordination.
