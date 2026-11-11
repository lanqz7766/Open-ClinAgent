# ClinAgent Repository Rules

This file is for coding agents working in this repository.

## Non-Negotiable Rules

1. Never commit or push `.env`, `.env.*`, API keys, tokens, copied credentials, or machine-specific secrets.
2. Never commit or push real patient data, MRI/DICOM/segmentation files, derived reports from real data, screenshots from real data, or manifests that reveal local data roots.
3. Keep active product and setup documentation in the root `README.md`. Do not use `docs/` as an active documentation tree.
4. Historical notes and retired plans belong only under `archive/`.
5. Treat `main` as a release branch: anything merged there must be safe for collaborators to clone and install without access to private servers, private data, or personal filesystem paths.

## What Must Stay Local

- `.env` and provider credentials
- `.env.*`
- local data roots and personal filesystem paths
- `.clinagent/`
- `reports/`
- `.clinagent/derived/`
- NIfTI, DICOM, segmentation, study exports, and real-case screenshots
- manifests, logs, notes, or screenshots that reveal local or server data roots
- any config, script default, README content, or other document containing personal home-directory paths, shared-storage mount paths, private hostnames or SSH aliases, real IPs, or real mounted-disk paths
- unrelated personal design drafts, local prompt files, or private ops notes

## Working Norms

- Treat this repository as a product repository, not a scratchpad.
- Prefer small, reviewable changes over broad speculative refactors.
- Keep README aligned with the shipped product surface.
- Prefer scenario and skill contributions over runtime changes when they can solve the problem cleanly.
- Any private infrastructure capability must be injected through environment variables. Never commit a real host, real path, or personal default into repo-tracked code, scripts, or docs.
- README and any commit-worthy setup script should explain how to configure optional private capabilities, not describe your personal environment.
- Terminal startup branding should use `frontend/public/clinagent-logo-mark.svg` as the canonical logo source, with ANSI color styling derived from that mark instead of ad hoc icons or emojis.

## Default Execution Environments

- Python commands must default to the repository virtual environment at `.venv/` when it exists.
- Prefer `.venv/bin/python` over system `python` or `python3` for tests, scripts, installs, and validation.
- Prefer `.venv/bin/python -m pytest` over bare `pytest` so the active interpreter and installed deps are unambiguous.
- If `.venv` is missing or broken, say so explicitly before falling back to any system interpreter.
- Frontend commands should run from `frontend/` and use the repo-local toolchain already present there, for example `npm run build` rather than global node tooling.

## Release Branch Rules

- `main` must remain release-ready, installable, and demoable.
- Collaborators should be able to `clone` the repo and `pip install` it without connecting to your private server.
- Private capabilities such as GPU-server access, MR-RATE indexing, SSH tunnels, or remote segmentation are optional enhancements, not required startup dependencies.
- If private capabilities are unavailable, the product should still degrade cleanly to mock/demo and general chat/workflow behavior, assuming the user provides their own API keys.

## Wheel And Release Validation

- Rebuild and validate a wheel whenever a change touches the public release surface.
- Treat these paths as release-surface changes:
  - `src/clinagent/**`
  - `skills/**`
  - `scenarios/**`
  - `src/clinagent/ui/demo-next/**`
- Representative core paths that always trigger wheel validation include:
  - `src/clinagent/engine/**`
  - `src/clinagent/platform/**`
  - `src/clinagent/gateway/**`
  - `src/clinagent/console/**`
  - `src/clinagent/families/**`
- Local-only scripts, private ops helpers, unshipped notes, and test data do not require wheel rebuilding unless they change the release experience for `clone` or `pip install` users.

## Private Remote Capability Gate

- Do not merge remote service, SSH tunnel, server bootstrap, or mounted-disk workflow changes into `main` by default.
- These changes may enter `main` only after all of the following are true:
  - server paths are fully parameterized
  - hostnames are fully parameterized
  - real personal defaults are removed
  - docs are generalized to environment-variable based setup
- If those conditions are not met, keep the change local or server-side only.

## Before Pushing

1. Run `python3 scripts/check_boundary_compliance.py`. If the script is unavailable, run an equivalent manual boundary review.
2. Check `git status` and `git diff --cached` for sensitive files, private paths, or local outputs.
3. Confirm `README.md` still matches actual shipped behavior and contains no personal environment details.
4. Make sure no new active docs were added outside the root README.
5. If the change touches the release surface:
   - run `cd frontend && npm run build` when UI source changed
   - rebuild the wheel with `python -m build` or equivalent
   - validate install from the built wheel in a clean environment, at minimum confirming `pip install dist/*.whl` succeeds
   - if UI source changed, ensure the corresponding `src/clinagent/ui/demo-next/**` build output is included in the staged diff
6. Treat any staged personal home-directory or shared-storage paths, private hostnames, real IPs, `.env`, `.clinagent`, reports, or real imaging artifacts as a release blocker.

## Optional Hook Setup

```bash
git config core.hooksPath .githooks
```
