# Ticket 10 & Workload Identity Federation Resources

## Knowledge

- [Document: `.scratch/deterministic-input-layer/impl/10-workload-identity-federation.md`](file:///d:/AI_tutor/wini_tabletop/.scratch/deterministic-input-layer/impl/10-workload-identity-federation.md)
  Specification ticket defining the requirements for billed CI WIF authentication.
- [Guide: `.github/BILLED_EVAL_SETUP.md`](file:///d:/AI_tutor/wini_tabletop/.github/BILLED_EVAL_SETUP.md)
  Complete operator manual for provisioning GCP Workload Identity Pool, Provider, Service Account, and GitHub Environment.
- [Workflow: `.github/workflows/ci.yml`](file:///d:/AI_tutor/wini_tabletop/.github/workflows/ci.yml)
  GitHub Actions workflow implementing the `billed-safety` and `billed-personal-data` jobs with OIDC authentication.
- [Google Cloud Documentation: Configuring Workload Identity Federation with GitHub Actions](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-providers#github-actions)
  Official GCP documentation on exchanging GitHub OIDC tokens for short-lived Google Cloud credentials.
- [GitHub Actions Documentation: About security hardening with OpenID Connect](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
  GitHub documentation on OpenID Connect tokens, claims (`sub`, `repository`, `environment`), and environment protection rules.

## Wisdom (Communities & Operations)

- GitHub Community / Actions Discussions: Best practices for environment-gated billing and preventing token abuse in PRs from forks.
- GCP IAM Best Practices: Principle of least privilege for Service Account impersonation via OIDC.
