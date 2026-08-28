# Mission: Master Ticket 10 (Workload Identity Federation for Billed CI)

## Why
Understand how secure, zero-static-secret authentication to Google Cloud Vertex AI works within GitHub Actions CI, and why this architecture protects both security and cloud billing budgets in production AI pipelines.

## Success looks like
- Can explain the step-by-step OIDC handshake between GitHub Actions and Google Cloud Workload Identity Federation (WIF).
- Understands why static JSON keys are prohibited in modern cloud AI CI/CD.
- Can explain the 5-step lifecycle of the `billed-safety` and `billed-personal-data` jobs in `.github/workflows/ci.yml`.
- Can configure and troubleshoot the GCP Workload Identity Pool, Provider, and GitHub `billed-eval` Environment.
- Understands how Tickets 10, 12, and 13 connect in the deterministic input layer roadmap.

## Constraints
- Hands-on codebase context (`wini_tabletop` repository).
- Focus on Google Cloud Vertex AI and GitHub Actions OIDC.

## Out of scope
- Non-GCP cloud federation (AWS STS, Azure AD).
- Full prompt engineering for child safety / PII (covered in Tickets 12 & 13).
