# Contributing to LXDash

This project runs CI on every PR to `main` and **blocks merge until all
gates pass**. The gate list below is enforced by GitHub branch protection
rules.

## Local development

### Backend

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt

# Lint and format
ruff check .
ruff format --check .

# Security scan
bandit -r . -ll

# Run tests (matches the CI job)
pytest
```

### Frontend

```bash
cd frontend
npm ci

npm run lint          # eslint
npm run type-check    # tsc --noEmit
npm test              # vitest
```

### Pre-commit checklist

Before pushing, run the four commands above. They reproduce what CI runs
and will tell you whether your PR is mergeable.

---

## Branch protection — `main`

Configured in **GitHub → Settings → Branches → Branch protection rules
→ `main`**. The rules below must be enabled so the gates actually block.

### Required status checks

Tick every check listed here. A missing check here means GitHub will
allow merges with that check failing.

#### `backend` workflow

- `ruff (lint + format)`
- `bandit (security scan)`
- `hadolint (Dockerfile)`
- `pytest`
- `trivy (image vulnerability scan)`

#### `frontend` workflow

- `eslint`
- `tsc --noEmit`
- `vitest`
- `hadolint (Dockerfile)`
- `trivy (image vulnerability scan)`

### Other recommended settings

- ✅ **Require a pull request before merging**
- ✅ **Require approvals:** 1
- ✅ **Dismiss stale pull request approvals when new commits are pushed**
- ✅ **Require linear history** (no merge commits)
- ✅ **Include administrators** (admins cannot bypass)
- ❌ **Allow force pushes**
- ❌ **Allow deletions**

---

## What each gate catches

| Gate | Catches |
|---|---|
| `ruff check` | Unused imports, undefined names, deprecated typing, missing exception chains (`raise ... from exc`), overly complex comprehensions |
| `ruff format --check` | Style drift; format is enforced so diffs stay minimal |
| `bandit` | Hardcoded passwords, `eval`, `subprocess` without `shell=False`, weak crypto |
| `hadolint` | Dockerfile anti-patterns (`:latest`, unpinned versions, missing `--no-install-recommends`, root user) |
| `pytest` | Unit-test regressions in config, auth, audit, health, seed |
| `eslint` | React hooks violations, undefined variables, unsafe type assertions |
| `tsc --noEmit` | Type errors that would otherwise only surface at build time |
| `vitest` | Unit-test regressions in shared helpers (`cn`, `formatBytes`, `formatRelativeTime`) |
| `trivy` | Known CVEs in base images or pip/npm dependencies at HIGH or CRITICAL severity |

---

## Adding a new dep

- **Python:** add to `backend/requirements.txt` (runtime) or `backend/requirements-dev.txt` (test/lint only). Pin the version. Then `pip install -r ...` locally and commit.
- **JS:** add to `frontend/package.json` `dependencies` (or `devDependencies` for build-time only). Then `npm install` to update `package-lock.json` and commit both.

CI installs pinned versions, so a missing lockfile update is a CI failure
(but only on first run — npm ci is strict).

## Adding a new gate

If you need a new gate (e.g. `mypy`, `prettier`):

1. Add the tool config to `backend/pyproject.toml` or `frontend/eslint.config.js` / `vitest.config.ts`.
2. Add a new job to `.github/workflows/backend.yml` or `frontend.yml`.
3. Add the new check name to the "Required status checks" list above (and to the GitHub repo settings).
4. Update this document.

Do not silently add gates — every gate here is also a hard requirement
for the PR to merge.

## Trivy exceptions

Trivy fails the build on CRITICAL/HIGH CVEs. If you need to merge a
known-vulnerable image:

- Don't. Pin the base image to a patched tag and re-run.
- If a CVE has no upstream fix, open an issue describing the exposure and
  get an explicit maintainer decision before changing `severity:` in
  the workflow.

SARIF output is uploaded to the **Security** tab for every run, so the
vulnerability history is auditable.