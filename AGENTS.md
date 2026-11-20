# ResQ — Repository Instructions for All AI Agents

These rules apply to every AI coding agent and assistant working in this repository, whatever the tool. Tool-specific additions live in that tool's own file (for example `CLAUDE.md`).

## 1. Project Context & Documentation
- **Platform:** ResQ Disaster Response Coordination Hub for Gujarat (FastAPI + Neon PostgreSQL PostGIS + Next.js 16).
- **Architecture:** Read `docs/architecture/ARCHITECTURE.md` before architectural or cross-module changes.
- **API Contracts:** `docs/architecture/api_contracts.md` defines the REST contracts and the standard error format.
- **Environment Variables:** `docs/architecture/env-variables.md` lists supported configuration (names only, never values).
- **Topic Rules:** Load the matching file in `.agents/rules/` for detail: `architecture.md`, `backend-database.md`, `frontend.md`, `security.md`.
- **AI Workflow:** `docs/guides/AI_WORKFLOW.md` describes the supported agent modes and the local orchestration pipeline.

## 2. Core Engineering Rules
- **Inspect First:** Inspect existing code, dependencies, and docs before making changes. Search `backend/app/` and `frontend/src/` for reusable services, components, and types.
- **Reuse Existing Code:** Reuse established services, utilities, schemas, and UI components; do not build duplicate functionality.
- **Zero Duplicate Files:** Never create redundant, duplicate, or unnecessary files.
- **Conventions & Architecture:** Follow existing folder structure, naming conventions, and FastAPI / Next.js patterns.
- **Minimal Changes:** Make minimal, targeted changes strictly focused on the requested task. Avoid unrelated refactoring.
- **Verify & Test:** Run relevant unit, integration, and lint checks after changes.
- **Review Diff:** Inspect the final `git diff` before reporting completion to confirm there are no unintended edits.

## 3. Standard Verification Commands
- Backend unit tests: `python -m pytest backend/tests/test_units.py -v`
- Full backend suite (needs PostGIS): set `TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/drch_test"`, then `python -m pytest backend/tests/ -v --tb=short`
- Backend lint: `python -m ruff check backend/`
- Audit hash-chain verification: `cd backend && python -m app.cli verify-audit`
- Frontend typecheck and build: `cd frontend && npm run build`

## 4. DRCH Technical Constraints
- **Database:** Neon PostgreSQL 16 with PostGIS. Never introduce Supabase Auth, `auth.users`, `auth.uid()`, or Supabase-specific SQL/triggers.
- **Authentication & RBAC:** Application-managed authentication; preserve Argon2id password hashing, TOTP MFA, and session/token revocation.
- **Audit Logging:** Maintain append-only, SHA-256 hash-chained audit logging with trigger-enforced immutability. State transitions must write to `audit_logs`.
- **AI Boundaries:** AI recommendations are strictly advisory and stored separately (`triage_results`). Never automate dispatch, priority change, or incident verification.
- **Human-in-the-Loop:** Human dispatcher approval is required for incident verification, dispatch, escalation, and closure.
- **Concurrency:** Use `SELECT ... FOR UPDATE` when allocating resources in `backend/app/services/resources.py`.
- **Strict Scenarios:** Only `cyclone`, `industrial_fire`, and `urban_flooding` are supported.
- **Privacy & PII:** Protect reporter PII and sensitive operational data. Truncate public incident coordinates to 4 decimal places.
- **Simulation Transparency:** Clearly label synthetic/fallback alert feeds and sandbox payment flows.

## 5. Git Restrictions
- NEVER automatically commit, push, merge, reset, or rewrite Git history. This covers `git commit`, `git push`, `git merge`, `git reset`, `git clean`, and `git rebase`, and merging a pull request. The human performs these.
- Agents draft commit messages, PR descriptions, and issues, and give the human the exact command to run.

## 6. Commits, Pull Requests & Issues
- **Conventional Commits:** `type(scope): imperative summary`, lowercase, no trailing period. Allowed types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `revert`. Scope is the module, for example `citizen`, `dm`, `field`, `security`, `ai-workers`, `frontend`. Mark breaking changes with `!` or a `BREAKING CHANGE:` footer. Use one type per concern; split unrelated docs and code into separate commits.
- **Length and description:** The subject is in the imperative mood ("add", not "added") and says clearly what changed. There is no hard character limit: never shorten, truncate or abbreviate a subject or body just to fit a length; clarity wins over brevity, though a subject that fits on one readable line is still preferred. Every commit beyond a trivial one has a blank line and a full description body that explains what changed and why, which areas or files it affects, how it was verified, and any trade-off or follow-up. Do not hard-wrap the body at a fixed width. No vague subjects such as "fix bug", "update files" or "wip". Reference issues in a footer (`Refs #123`, `Fixes #123`).
- **AI co-author trailers:** Commits do not carry an AI co-author or attribution trailer. The only exceptions are commits made on an open PR branch that apply review feedback or fix bugs found in that PR (including CI failures); those may end with the agent's co-author trailer. General commits (features, refactors, docs, tests, chores, and a PR's initial commits) never carry one. Issues and PR descriptions never carry AI attribution.
- **Pull requests:** Use `.github/PULL_REQUEST_TEMPLATE.md` exactly. Keep every section (Summary, Related issue, Changes, Verification, Screenshots, Checklist) and tick only what was actually done. The title is a Conventional Commit line. Write "None" or "Not applicable" instead of deleting a section.
- **Issues:** Use the forms in `.github/ISSUE_TEMPLATE/` (`bug_report.yml` for defects, `feature_request.yml` for enhancements) and fill every required field. Keep the title prefix (`[Bug]: `, `[Feature]: `). Blank issues are disabled.
- **PR scope:** Include only files that belong to the task. Never stage unrelated untracked files, and never put secrets or real personal data in a commit, PR, or issue.

## 7. Response Summary
Summarize changes made, reused code/modules, tests run and their results, and any remaining issues or manual steps.
