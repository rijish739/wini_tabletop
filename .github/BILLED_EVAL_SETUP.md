# Billed-Eval CI Setup Guide

This document explains how to configure Workload Identity Federation (WIF) and the `billed-eval`
GitHub Environment so the `billed-safety` and `billed-personal-data` CI jobs can authenticate to
Vertex AI **without a static service-account key**.

Until both steps below are complete every run of the billed jobs will fail at the guard step with a
clear error message — that is the intended "unconfigured" failure state.

---

## Why WIF, not a key file?

Service-account key files can be leaked through the repository or logs, rotate awkwardly, and give
persistent access. Workload Identity Federation issues a short-lived OIDC token for each workflow
run; there is nothing persistent to leak or rotate.

The IAM binding below grants access only when the token came from **this repository's `billed-eval`
environment** — so a fork or an unapproved branch gets nothing.

---

## Step 1 — GCP: create the Workload Identity pool and provider

Run the following `gcloud` commands once in the project that owns the Vertex AI quota. Replace
`PROJECT_ID` with your GCP project ID throughout.

```bash
PROJECT_ID=<your-gcp-project-id>
GITHUB_ORG=<github-org-or-username>      # e.g. jainprathwi-stack
GITHUB_REPO=wini_tabletop                # repository name (not full path)
POOL_ID=github-actions-pool
PROVIDER_ID=github-oidc

# 1. Create the Workload Identity pool
gcloud iam workload-identity-pools create "$POOL_ID" \
  --project="$PROJECT_ID" \
  --location="global" \
  --display-name="GitHub Actions pool"

# 2. Add the GitHub OIDC provider
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project="$PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="$POOL_ID" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment" \
  --attribute-condition="assertion.repository == '${GITHUB_ORG}/${GITHUB_REPO}' && assertion.environment == 'billed-eval'"
```

The `attribute-condition` restricts the provider so only tokens from **this repo's `billed-eval`
environment** are accepted — not a fork, not a different environment, not a push without approval.

### 1b — Create (or designate) the service account

Create a dedicated service account for CI evals. It needs only the permissions required to invoke
the specific Vertex AI models used by `eval/safety_eval.py` and `eval/personal_data_eval.py`.

```bash
SA_NAME=wini-billed-ci
gcloud iam service-accounts create "$SA_NAME" \
  --project="$PROJECT_ID" \
  --display-name="Wini billed-eval CI runner"

# Grant Vertex AI user role (adjust to least-privilege after evals are shipped)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### 1c — Bind the pool provider to the service account

```bash
POOL_RESOURCE="projects/$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')/locations/global/workloadIdentityPools/$POOL_ID/providers/$PROVIDER_ID"

gcloud iam service-accounts add-iam-policy-binding \
  "${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_RESOURCE%/providers/*}/attribute.environment/billed-eval"
```

### 1d — Record the provider resource name

```bash
gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --project="$PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="$POOL_ID" \
  --format="value(name)"
```

The output looks like:
```
projects/123456789/locations/global/workloadIdentityPools/github-actions-pool/providers/github-oidc
```

This is the value you put in the `WIF_PROVIDER` secret (Step 2).

---

## Step 2 — GitHub: create the `billed-eval` environment and add secrets

### 2a — Create the environment with required reviewers

1. Go to **Settings → Environments → New environment** in the GitHub repo.
2. Name it exactly **`billed-eval`** (the workflow references this name).
3. Under **Deployment protection rules**, enable **Required reviewers** and add at least one
   reviewer (the project owner, a team lead, or a dedicated security reviewer).
4. Leave **"Allow administrators to bypass configured protection rules"** unchecked if you want
   the gate to apply to everyone.
5. Do **not** add branch filters — the required-reviewer gate is the only guard. Path-based
   or branch-based auto-skips are explicitly out of scope (spec §10).

### 2b — Add the secrets to the `billed-eval` environment

In the environment's **Secrets** section (not the repo-level secrets), add:

| Secret name          | Value                                                                       |
|----------------------|-----------------------------------------------------------------------------|
| `WIF_PROVIDER`       | The provider resource name from Step 1d (the long `projects/…` string)     |
| `WIF_SERVICE_ACCOUNT`| `wini-billed-ci@PROJECT_ID.iam.gserviceaccount.com`                        |

Adding them as **environment secrets** (rather than repository secrets) means they are only
available when the environment gate fires — i.e., after a reviewer approves the run.

---

## Verification

Once both steps are done, trigger a workflow run and approve the `billed-eval` environment gate.
The guard step should pass (both secrets are non-empty), the WIF auth step should succeed, and the
jobs will exit non-zero at the stub step with:

```
WIF auth succeeded — the environment gate and federation wiring are proven.
Exiting non-zero so this job does not silently pass before the eval exists.
```

That is the correct state until ticket 12 (`billed-safety`) and ticket 13 (`billed-personal-data`)
ship their eval steps.

---

## Cost note

- `billed-safety` calls `eval/safety_eval.py --collect` (ticket 12): one Vertex AI call per
  uncached row in the blind corpora. New rows accumulate costs; cached rows are free.
- `billed-personal-data` calls `eval/personal_data_eval.py --collect` (ticket 13): one call per
  uncached row, including the ≥500-row maths-dense corpus.
- The reviewer approving the environment gate is the person authorising the spend. The run logs
  will print the row count and estimated cost before making any calls (once tickets 12/13 ship).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| Guard fails: `WIF_PROVIDER not configured` | Secret not added to the `billed-eval` environment (Step 2b) |
| Guard fails: `WIF_SERVICE_ACCOUNT not configured` | Secret not added (Step 2b) |
| Auth step fails: `Error creating token` | Provider resource name is wrong, or the attribute-condition rejects the token (check environment name matches `billed-eval` exactly) |
| Auth step fails: `Permission denied` | IAM binding in Step 1c is missing or uses the wrong principal format |
| Job never runs / waits indefinitely | No reviewer has approved the `billed-eval` gate for this run |
