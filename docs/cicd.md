# CI/CD

## Current Workflow Model

`mitosis-oasis` uses an inlined GitHub Actions workflow in `.github/workflows/ci.yml`.

Reason:

- the repo is public
- `mitosis-cicd` is private
- GitHub reusable workflow visibility makes direct reuse impractical here

This means workflow changes that land in `mitosis-cicd` do not automatically reach OASIS. The OASIS workflow must be reviewed manually when shared CI behavior changes.

## Pipeline Shape

```text
python-ci
  -> docker build + push (main push only)
  -> deploy (currently disabled)
```

## Secrets and Permissions

| Secret | Purpose |
|---|---|
| `GITHUB_TOKEN` / packages write | GHCR publish |
| `DROPLET_IP`, `DROPLET_USER`, `DROPLET_SSH_KEY` | Reserved for deploy path when re-enabled |

## Current Deploy Status

The deploy job is intentionally disabled in the workflow. The inline comment documents that the former production droplet target was deleted on 2026-04-12 and OASIS has no active deploy target until it is migrated or a new host is designated.

That status is part of the current production truth and must stay explicit in docs until the target changes.

## CI Maintenance Rule

When `mitosis-cicd` reusable workflows evolve, manually compare OASIS's inlined `ci.yml` against the shared contract and decide whether to mirror the change here.
