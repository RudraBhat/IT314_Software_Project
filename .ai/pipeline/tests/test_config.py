"""Tests for pipeline configuration loading, alias resolution, and validation."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.claude_runner import resolve_model, validate_model_identifier
from pipeline.orchestrator import PipelineOrchestrator


def test_validate_model_identifier():
    # Valid model identifiers
    assert validate_model_identifier("sonnet")
    assert validate_model_identifier("opus")
    assert validate_model_identifier("claude-3-5-sonnet-20241022")
    assert validate_model_identifier("claude-3-haiku:preview")
    assert validate_model_identifier("model_1.2")
    assert validate_model_identifier("custom[model]")

    # Invalid model identifiers (flag injection, spaces, shell injection)
    assert not validate_model_identifier("-model")
    assert not validate_model_identifier("--danger")
    assert not validate_model_identifier("model with spaces")
    assert not validate_model_identifier("model;rm -rf /")
    assert not validate_model_identifier("$(whoami)")
    assert not validate_model_identifier("`cat /etc/passwd`")
    assert not validate_model_identifier("")
    assert not validate_model_identifier(None)  # type: ignore[arg-type]


def test_default_config_loading(tmp_repo: Path):
    orch = PipelineOrchestrator(tmp_repo)
    config = orch.config

    assert "claude_command" in config
    assert "role_models" in config
    assert "model_aliases" in config
    assert "model_fallbacks" in config
    assert config["role_models"]["planner"] is None
    assert config["role_models"]["implementer"] is None
    assert config["role_models"]["reviewer"] is None


def test_legacy_model_mapping(tmp_repo: Path):
    custom_cfg = {
        "model": "claude-3-5-sonnet-20241022",
        "permission_mode": "default",
    }
    cfg_file = tmp_repo / ".ai" / "pipeline" / "legacy_config.json"
    cfg_file.write_text(json.dumps(custom_cfg), encoding="utf-8")

    orch = PipelineOrchestrator(tmp_repo, config_path=cfg_file)
    assert orch.config["role_models"]["planner"] == "claude-3-5-sonnet-20241022"
    assert orch.config["role_models"]["implementer"] == "claude-3-5-sonnet-20241022"
    assert orch.config["role_models"]["reviewer"] == "claude-3-5-sonnet-20241022"


def test_reviewer_fallback_is_strictly_prohibited(tmp_repo: Path):
    custom_cfg = {
        "role_models": {
            "planner": "sonnet",
            "implementer": "opus",
            "reviewer": "opus",
        },
        "model_fallbacks": {
            "planner": ["sonnet"],
            "reviewer": ["sonnet", "haiku"],  # Must be stripped
        },
    }
    cfg_file = tmp_repo / ".ai" / "pipeline" / "reviewer_fb_config.json"
    cfg_file.write_text(json.dumps(custom_cfg), encoding="utf-8")

    orch = PipelineOrchestrator(tmp_repo, config_path=cfg_file)
    # Reviewer fallback must be stripped to empty list
    assert orch.config["model_fallbacks"]["reviewer"] == []


def test_resolve_model_via_aliases():
    config = {
        "model_aliases": {
            "sonnet": "claude-3-5-sonnet-20241022",
            "opus": "claude-3-opus-20240229",
        },
        "role_models": {
            "planner": "sonnet",
            "implementer": "opus",
            "reviewer": "claude-3-5-sonnet-20241022",
        },
    }

    assert resolve_model(config, "planner") == "claude-3-5-sonnet-20241022"
    assert resolve_model(config, "implementer") == "claude-3-opus-20240229"
    assert resolve_model(config, "reviewer") == "claude-3-5-sonnet-20241022"


def test_resolve_model_rejects_invalid_identifier():
    config = {
        "role_models": {
            "planner": "--malicious-flag",
        },
    }
    assert resolve_model(config, "planner") is None

