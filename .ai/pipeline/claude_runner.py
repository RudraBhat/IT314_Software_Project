"""Claude Code CLI Integration Runner.

Executes Claude Code non-interactively using the developer's existing
Claude Pro / Team authentication via `claude -p`.
Includes typed failure classification, alias resolution, dry-run simulation,
and quota-safe execution.
"""

from __future__ import annotations

import enum
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("drch.ai.claude")

# Strict regex for model identifiers: avoids leading dashes (flag injection) and shell metachars
MODEL_ID_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,63}$")


class ClaudeFailureKind(enum.Enum):
    CLI_NOT_INSTALLED = "CLI_NOT_INSTALLED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TIMEOUT = "TIMEOUT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    OTHER_ERROR = "OTHER_ERROR"


@dataclass
class ClaudeResult:
    ok: bool
    text: Optional[str] = None
    kind: Optional[ClaudeFailureKind] = None
    model_requested: Optional[str] = None
    model_used: Optional[str] = None
    returncode: int = 0
    detail: str = ""
    fallback_hops: List[Dict[str, str]] = field(default_factory=list)


def redact_secrets(text: str) -> str:
    """Redact sensitive API keys, tokens, and authorization headers from logs."""
    if not text:
        return ""

    # Redact sk- style tokens and Bearer tokens
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED_API_KEY]", text)
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]{15,}", "Bearer [REDACTED_TOKEN]", redacted)

    # Redact values of sensitive environment variables
    for key, val in os.environ.items():
        if any(term in key.upper() for term in ("KEY", "SECRET", "TOKEN", "PASSWORD")) and len(val) >= 6:
            redacted = redacted.replace(val, f"[REDACTED_{key}]")

    return redacted[-1000:]


def classify_failure(returncode: int, stdout: str, stderr: str) -> ClaudeFailureKind:
    """Classify Claude Code CLI failure into typed failure categories.

    Quota errors are evaluated with highest priority to prevent accidental model-switching.
    Ambiguous or unknown text safely fails closed to OTHER_ERROR.
    """
    combined = (stdout + "\n" + stderr).lower()

    # 1. Quota exhaustion patterns (highest priority)
    quota_patterns = [
        "usage limit",
        "rate limit",
        "quota",
        "credit balance",
        "exceeded your current quota",
        "rate_limit_error",
        "429",
        "too many requests",
        "overloaded",
    ]
    is_quota = any(p in combined for p in quota_patterns)

    # 2. Model unavailable patterns
    model_patterns = [
        "model not found",
        "invalid model",
        "unknown model",
        "does not have access to model",
        "model_not_found",
        "model is not available",
        "unrecognized model",
    ]
    is_model_unavail = any(p in combined for p in model_patterns)

    # Quota text always takes precedence over model wording
    if is_quota:
        return ClaudeFailureKind.QUOTA_EXHAUSTED

    if is_model_unavail:
        return ClaudeFailureKind.MODEL_UNAVAILABLE

    # 3. Authentication required
    auth_patterns = [
        "not authenticated",
        "auth required",
        "please log in",
        "unauthorized",
        "401",
        "invalid api key",
        "token expired",
        "run claude to sign in",
    ]
    if any(p in combined for p in auth_patterns):
        return ClaudeFailureKind.AUTH_REQUIRED

    # 4. Permission denied
    if "permission denied" in combined or "403" in combined or "forbidden" in combined:
        return ClaudeFailureKind.PERMISSION_DENIED

    # 5. Timeout
    if "timed out" in combined or "timeout" in combined or returncode == -1:
        return ClaudeFailureKind.TIMEOUT

    return ClaudeFailureKind.OTHER_ERROR


def validate_model_identifier(model_id: str) -> bool:
    """Validate that model string matches strict identifier regex with no shell injections."""
    if not model_id or not isinstance(model_id, str):
        return False
    return bool(MODEL_ID_REGEX.match(model_id.strip()))


def resolve_model(config: Dict[str, Any], role: str) -> Optional[str]:
    """Resolve the model identifier for a given role from config without network calls.

    Resolution order:
    1. role_models[role] -> alias -> model_aliases[alias]
    2. fallback to legacy models[role] or model key
    """
    role_models = config.get("role_models") or config.get("models") or {}
    raw_model = role_models.get(role)

    # Legacy fallback: single model key in config
    if raw_model is None and "model" in config:
        raw_model = config["model"]

    if not raw_model:
        return None

    raw_str = str(raw_model).strip()
    aliases = config.get("model_aliases") or {}
    resolved = aliases.get(raw_str, raw_str)

    if not validate_model_identifier(resolved):
        logger.warning(f"Invalid model identifier rejected: {resolved}")
        return None

    return resolved


def detect_claude_cli() -> Dict[str, Any]:
    """Detect if the Claude Code CLI is installed and check its version."""
    cli_path = shutil.which("claude")
    if not cli_path:
        return {"installed": False, "path": None, "version": None}

    version = None
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if proc.returncode == 0:
            version = proc.stdout.strip()
    except Exception:
        version = "detected (version check timed out)"

    return {
        "installed": True,
        "path": cli_path,
        "version": version or "unknown",
    }


def invoke_claude_detailed(
    prompt: str,
    config: Dict[str, Any],
    label: str,
    cwd: Path,
    role: str = "implementer",
    dry_run: bool = False,
    timeout_seconds: int = 300,
) -> ClaudeResult:
    """Invoke Claude Code CLI with typed failure classification and quota-safe fallbacks."""
    requested_model = resolve_model(config, role)

    if dry_run:
        print(f"  [DRY RUN] Simulating Claude Code execution for: {label} (role: {role}, model: {requested_model or 'default'})")
        if "plan" in label.lower():
            text = (
                f"### [Simulated Plan for: {label}]\n\n"
                "1. Scope: Identified affected files in backend and frontend.\n"
                "2. Constraints: Verified Neon PostgreSQL + PostGIS compliance.\n"
                "3. Implementation steps:\n"
                "   - Update endpoint logic in `backend/app/routers/`\n"
                "   - Add unit test in `backend/tests/`\n"
                "4. Testing: Run `python -m pytest backend/tests/test_units.py`."
            )
        elif "implementation" in label.lower():
            text = (
                f"### [Simulated Implementation for: {label}]\n\n"
                "Simulated code changes applied. Zero files were modified during dry-run."
            )
        elif "review" in label.lower():
            text = (
                f"### [Simulated Code Review for: {label}]\n\n"
                "**Verdict:** APPROVED\n\n"
                "- [COMPLIANT] Concurrency locking rules adhered to.\n"
                "- [COMPLIANT] Zero Supabase dependencies introduced.\n"
                "- [COMPLIANT] Scenario Scope: COMPLIANT\n"
                "- [COMPLIANT] AI Advisory Boundary: COMPLIANT\n"
            )
        else:
            text = f"[Simulated response for: {label}]"

        return ClaudeResult(
            ok=True,
            text=text,
            model_requested=requested_model,
            model_used=requested_model or "simulated-default",
            returncode=0,
        )

    cli_info = detect_claude_cli()
    if not cli_info["installed"]:
        print("❌ Error: Claude Code CLI (`claude`) is not installed or not in PATH.")
        return ClaudeResult(
            ok=False,
            kind=ClaudeFailureKind.CLI_NOT_INSTALLED,
            detail="Claude Code CLI (`claude`) is not installed or not in PATH.",
        )

    # Fallback chain preparation (Hard rule: Reviewer role has NO fallback)
    candidate_models: List[Optional[str]] = [requested_model]
    if role != "reviewer":
        fallbacks = (config.get("model_fallbacks") or {}).get(role, [])
        for fb in fallbacks:
            fb_resolved = (config.get("model_aliases") or {}).get(fb, fb)
            if validate_model_identifier(fb_resolved) and fb_resolved not in candidate_models:
                candidate_models.append(fb_resolved)

    fallback_hops: List[Dict[str, str]] = []

    for idx, model_to_use in enumerate(candidate_models):
        if idx > 0:
            hop = {
                "from": str(candidate_models[idx - 1]),
                "to": str(model_to_use),
                "reason": "MODEL_UNAVAILABLE",
            }
            fallback_hops.append(hop)
            print(f"  🔄 Model fallback hop: {hop['from']} -> {hop['to']}")

        cmd: List[str] = list(config.get("claude_command", ["claude", "-p"]))
        if model_to_use:
            cmd += ["--model", model_to_use]

        perm_mode = config.get("permission_mode", "default")
        cmd += ["--permission-mode", perm_mode, prompt]

        print(f"  ⏳ Running Claude Code CLI: {label} (model: {model_to_use or 'default'})...")

        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout_seconds,
            )

            if proc.returncode == 0:
                return ClaudeResult(
                    ok=True,
                    text=proc.stdout.strip(),
                    model_requested=requested_model,
                    model_used=model_to_use or "cli-default",
                    returncode=0,
                    fallback_hops=fallback_hops,
                )

            # Failure occurred: Classify outcome
            failure_kind = classify_failure(proc.returncode, proc.stdout, proc.stderr)
            err_detail = redact_secrets(proc.stderr.strip() or proc.stdout.strip())
            print(f"  ❌ Claude Code CLI exited with code {proc.returncode} ({failure_kind.value})")

            # Quota exhausted: STRICTLY DO NOT FALLBACK OR RETRY
            if failure_kind == ClaudeFailureKind.QUOTA_EXHAUSTED:
                return ClaudeResult(
                    ok=False,
                    kind=failure_kind,
                    model_requested=requested_model,
                    model_used=model_to_use,
                    returncode=proc.returncode,
                    detail=err_detail,
                    fallback_hops=fallback_hops,
                )

            # Model unavailable: Try next fallback if candidate list has remaining options
            if failure_kind == ClaudeFailureKind.MODEL_UNAVAILABLE and idx < len(candidate_models) - 1:
                continue

            # Other errors (Auth, Timeout, Permission): Do not retry
            return ClaudeResult(
                ok=False,
                kind=failure_kind,
                model_requested=requested_model,
                model_used=model_to_use,
                returncode=proc.returncode,
                detail=err_detail,
                fallback_hops=fallback_hops,
            )

        except subprocess.TimeoutExpired:
            print(f"  ❌ Claude Code CLI timed out after {timeout_seconds}s")
            return ClaudeResult(
                ok=False,
                kind=ClaudeFailureKind.TIMEOUT,
                model_requested=requested_model,
                model_used=model_to_use,
                returncode=-1,
                detail=f"Timed out after {timeout_seconds} seconds.",
                fallback_hops=fallback_hops,
            )
        except Exception as e:
            print(f"  ❌ Error executing Claude Code CLI: {e}")
            return ClaudeResult(
                ok=False,
                kind=ClaudeFailureKind.OTHER_ERROR,
                model_requested=requested_model,
                model_used=model_to_use,
                returncode=-1,
                detail=redact_secrets(str(e)),
                fallback_hops=fallback_hops,
            )

    return ClaudeResult(
        ok=False,
        kind=ClaudeFailureKind.MODEL_UNAVAILABLE,
        model_requested=requested_model,
        detail="All model fallbacks exhausted.",
        fallback_hops=fallback_hops,
    )


def invoke_claude(
    prompt: str,
    config: Dict[str, Any],
    label: str,
    cwd: Path,
    role: str = "implementer",
    dry_run: bool = False,
    timeout_seconds: int = 300,
) -> Optional[str]:
    """Backward-compatible wrapper returning Optional[str]."""
    res = invoke_claude_detailed(
        prompt=prompt,
        config=config,
        label=label,
        cwd=cwd,
        role=role,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
    )
    return res.text if res.ok else None
