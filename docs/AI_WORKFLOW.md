# DRCH AI Development Workflow Guide

This document describes the AI-assisted software engineering environment for the **Disaster Response Coordination Hub (DRCH)**. The repository supports three completely independent modes of operation:

- **Mode A: Google Antigravity Only** (Standalone IDE / Agent)
- **Mode B: Claude Code Only** (Terminal CLI / Claude Pro)
- **Mode C: Local Orchestration Pipeline** (Automated multi-stage coordination)

---

## 1. Core Engineering Invariants (All Modes)

Regardless of the tool used, all AI-generated code and architecture plans must adhere to DRCH standards:

1. **Database:** Neon PostgreSQL 16 with PostGIS. Strictly no Supabase Auth, `auth.users`, `auth.uid()`, or Supabase-specific triggers.
2. **Authentication & RBAC:** Application-managed authentication using Argon2id password hashing, TOTP MFA, and session revocation.
3. **Audit Trail:** Append-only SHA-256 hash-chained audit logging with trigger-enforced immutability.
4. **AI Boundaries:** AI recommendations are strictly advisory (`triage_results`). Human dispatcher approval is required for incident verification, dispatch, escalation, and closure.
5. **Disaster Scope:** Exactly 3 disaster scenarios (`cyclone`, `industrial_fire`, `urban_flooding`).
6. **Privacy:** Protect reporter PII. Public incident coordinates truncated to 4 decimal places.
7. **Git Safety:** AI tools are **strictly prohibited** from running `git commit`, `git push`, `git merge`, `git reset`, or rewriting Git history.

---

## 2. Mode A: Google Antigravity (Standalone)

Use Google Antigravity directly for feature development, bug fixes, refactoring, and interactive pairing without requiring Claude Code or external scripts.

### Configuration Structure
```text
├── AGENTS.md                  # Concise global instructions loaded on every turn
└── .agents/
    └── rules/
        ├── architecture.md     # Loaded on system architecture & API changes
        ├── backend-database.md # Loaded on FastAPI, SQL, PostGIS, worker changes
        ├── frontend.md         # Loaded on React, Next.js, UI changes
        └── security.md         # Loaded on Auth, RBAC, PII, Audit changes
```

### Usage
- Antigravity automatically detects the appropriate rules using dynamic `model_decision` triggers based on your prompt and modified files.
- You can work iteratively, asking Antigravity to run tests, inspect diffs, and generate changes.

---

## 3. Mode B: Claude Code CLI (Standalone)

Use Anthropic's Claude Code CLI directly in your terminal, authenticated via your Claude Pro / Team subscription.

### Configuration Structure
```text
├── CLAUDE.md                  # Imports @AGENTS.md and defines common dev commands
└── .claude/
    ├── settings.json          # Explicit deny permissions for mutating Git commands
    └── skills/                # Reusable slash commands
        ├── implement-feature/ # /implement-feature <description>
        ├── code-review/       # /code-review
        ├── debug/             # /debug <issue>
        ├── security-audit/    # /security-audit
        ├── database-review/   # /database-review
        ├── api-review/        # /api-review
        └── test-plan/         # /test-plan
```

### Usage
Run Claude Code in your terminal from the repository root:
```powershell
claude
```

Use the pre-configured skills inside the Claude Code session:
```text
/implement-feature "Add PostGIS spatial query for active cyclone incidents"
/code-review
/security-audit
```

All destructive git operations (`git commit`, `git push`, `git reset`, `git merge`, `gh pr merge`) are blocked by `.claude/settings.json`.

---

## 4. Mode C: Local AI Orchestration Pipeline

The Local AI Orchestrator coordinates multi-stage planning, implementation, verification, and code review across tools with built-in human approval gates.

**Primary Agent:** Google Antigravity is the primary development agent (`--agent antigravity`, default).
**Optional Reviewer:** Claude Code CLI operates as an optional independent reviewer (`--agent claude` or independent reviewer role). The orchestrator never requires Claude Code availability or subscription quota to execute Antigravity tasks.

### Pipeline Architecture (9 Stages)
1. **Stage 1: Initialization (`INITIALIZED`)** — Generates a unique task ID, initializes state in `.ai/tasks/<task_id>.json`, and acquires an exclusive filesystem lock (`.ai/tasks/<task_id>.lock`).
2. **Stage 2: Context Scan** — Scans the repository structure, filtering out binaries, caches, and `.env` files.
3. **Stage 3: Plan Generation (`PLANNING` → `PLAN_READY`)** — Generates an architecture-compliant implementation plan in `.ai/reports/<task_id>_plan.md` enforcing all DRCH constraints.
4. **Stage 4: Human Plan Approval Gate (`HUMAN_PLAN_APPROVAL`)** — Prompts the developer to approve the plan, revise it, or generate an Antigravity handoff instruction.
5. **Stage 5: Implementation Execution (`IMPLEMENTING`)** — 
   - **Antigravity Mode (Default):** Prepares workspace instructions at `.ai/handoffs/<task_id>_antigravity_handoff.md`, records handoff, and transitions to `HANDED_OFF_TO_ANTIGRAVITY`. Antigravity applies changes directly to the codebase.
   - **Claude Mode:** Non-interactively invokes `claude -p` using the developer's local Claude CLI subscription.
6. **Stage 6: Automated Verification (`VALIDATING`)** — Runs automated test suites and linters (`pytest`, `ruff`), capturing output in `.ai/reports/<task_id>_validation.md`.
   - **Fail-Closed Rule:** Any check failure, timeout, user skip, security skip, or 0 executed checks immediately results in `VALIDATION_FAILED` and blocks code review.
7. **Stage 7: Independent Code Review (`REVIEWING`)** — Inspects current staged and unstaged `git diff` against DRCH security standards and writes `.ai/reports/<task_id>_review.md`.
   - Reviewer model fallback is permanently disabled (strict policy).
   - If verdict is `REJECTED`, transitions to `REVIEW_REJECTED`.
   - If verdict is `APPROVED`, transitions to `READY_FOR_HUMAN_REVIEW`.
8. **Stage 8: Ready for Human Review (`READY_FOR_HUMAN_REVIEW`)** — Presents diff fingerprints and validation/review reports to the human developer.
9. **Stage 9: Human Acknowledgment & Completion (`COMPLETED`)** — The developer confirms completion via interactive TTY by typing the exact phrase:
   `I have reviewed the diff and reports for <task_id>`.
   A task can **never** become `COMPLETED` automatically or without human acknowledgment.

### Explicit Failure & Pause States
- `PLAN_FAILED`: Plan generation failed or was aborted.
- `IMPLEMENTATION_FAILED`: Code changes failed to apply.
- `VALIDATION_FAILED`: Any test, lint, or safety check failed or was skipped.
- `REVIEW_FAILED`: Review generation failed.
- `REVIEW_REJECTED`: Code reviewer issued a `REJECTED` verdict.
- `PAUSED_QUOTA_EXHAUSTED`: Claude quota limit reached; pipeline halts without retrying.
- `HANDED_OFF_TO_ANTIGRAVITY`: Work handed off to Google Antigravity for direct workspace changes.
- `HALTED_BY_USER`: Explicitly paused or stopped by the developer.

### CLI Usage

#### Check Environment Health
```powershell
python scripts/ai-dev.py --doctor
```

#### Safe Static Model Inspection (Zero Quota Spent)
```powershell
python scripts/ai-dev.py --check-models
```

#### Start a Task with Antigravity (Default)
```powershell
python scripts/ai-dev.py --task "Implement cyclone alert endpoint" --agent antigravity
```

#### Start a Task in Dry-Run Mode (Simulation)
```powershell
python scripts/ai-dev.py --task "Implement cyclone alert endpoint" --dry-run
```

#### Resume a Task after Antigravity Implementation
After editing code in Antigravity, resume verification and review:
```powershell
python scripts/ai-dev.py --resume <task_id> --step validate
```

#### Acknowledge Review and Complete Task
```powershell
python scripts/ai-dev.py --ack-review <task_id>
```
*(Requires interactive terminal and exact confirmation phrase).*

#### Generate Antigravity Handoff on Resumed Task
```powershell
python scripts/ai-dev.py --resume <task_id> --handoff
```

#### Record Antigravity Execution Record
```powershell
python scripts/ai-dev.py --record-impl <task_id>
```

#### List All Registered Tasks
```powershell
python scripts/ai-dev.py --list-tasks
```

#### Run Pipeline Unit & Regression Tests
```powershell
python -m pytest .ai/pipeline/tests/ -v
```

---

## 5. Artifact & File Hygiene

- Runtime output directories (`.ai/tasks/`, `.ai/reports/`, `.ai/handoffs/`) are ignored by `.gitignore` and created on demand.
- Local developer settings (`.claude/settings.local.json`, `.agents/settings.local.json`) are ignored.
- Repository configuration files (`AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, `.claude/skills/`, `.agents/rules/`, `scripts/ai-dev.py`) remain tracked in Git for team-wide use.

