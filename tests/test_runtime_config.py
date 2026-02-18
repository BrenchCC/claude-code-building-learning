"""Unit tests for shared runtime option parsing."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import run_tests
from utils.runtime_config import add_runtime_args, runtime_options_from_args


def _parse_with_args(arg_list):
    """Build parser with runtime args and parse provided argv list."""
    parser = argparse.ArgumentParser()
    add_runtime_args(parser)
    return parser.parse_args(arg_list)


def _set_env(overrides):
    """Set env variables and return previous snapshot for restoration."""
    before = {}
    for key, value in overrides.items():
        before[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return before


def _restore_env(snapshot):
    """Restore env variables from snapshot."""
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_cli_overrides_env():
    """CLI flags must override environment variables."""
    env_backup = _set_env(
        {
            "AGENT_SHOW_LLM_RESPONSE": "0",
            "AGENT_STREAM": "1",
            "AGENT_THINKING_MODE": "auto",
            "AGENT_REASONING_EFFORT": "low",
            "AGENT_REASONING_PREVIEW_CHARS": "999",
            "AGENT_SAVE_SESSION": "0",
            "AGENT_SESSION_DIR": "env_sessions",
        }
    )

    try:
        args = _parse_with_args(
            [
                "--show-llm-response",
                "--no-stream",
                "--thinking",
                "off",
                "--reasoning-effort",
                "high",
                "--reasoning-preview-chars",
                "120",
                "--save-session",
                "--session-dir",
                "cli_sessions",
            ]
        )
        options = runtime_options_from_args(args)

        assert options.show_llm_response is True
        assert options.stream is False
        assert options.thinking_mode == "off"
        assert options.reasoning_effort == "high"
        assert options.reasoning_preview_chars == 120
        assert options.save_session is True
        assert str(options.session_dir) == "cli_sessions"
    finally:
        _restore_env(env_backup)

    print("PASS: test_cli_overrides_env")
    return True


def test_env_parsing_without_cli():
    """ENV values should be parsed when CLI does not override them."""
    env_backup = _set_env(
        {
            "AGENT_SHOW_LLM_RESPONSE": "true",
            "AGENT_STREAM": "yes",
            "AGENT_THINKING_MODE": "on",
            "AGENT_REASONING_EFFORT": "medium",
            "AGENT_THINKING_CAPABILITY": "toggle",
            "AGENT_REASONING_PREVIEW_CHARS": "88",
            "AGENT_SAVE_SESSION": "1",
            "AGENT_SESSION_DIR": "from_env",
            "AGENT_THINKING_PARAM_STYLE": "reasoning_effort",
        }
    )

    try:
        args = _parse_with_args([])
        options = runtime_options_from_args(args)

        assert options.show_llm_response is True
        assert options.stream is True
        assert options.thinking_mode == "on"
        assert options.reasoning_effort == "medium"
        assert options.thinking_capability == "toggle"
        assert options.reasoning_preview_chars == 88
        assert options.save_session is True
        assert str(options.session_dir) == "from_env"
        assert options.thinking_param_style == "reasoning_effort"
    finally:
        _restore_env(env_backup)

    print("PASS: test_env_parsing_without_cli")
    return True


def test_invalid_env_falls_back_to_defaults():
    """Invalid ENV tokens should fall back to safe defaults."""
    env_backup = _set_env(
        {
            "AGENT_SHOW_LLM_RESPONSE": "maybe",
            "AGENT_STREAM": "not_bool",
            "AGENT_THINKING_MODE": "weird",
            "AGENT_REASONING_EFFORT": "ultra",
            "AGENT_THINKING_CAPABILITY": "unknown",
            "AGENT_REASONING_PREVIEW_CHARS": "nan",
            "AGENT_SAVE_SESSION": "invalid",
            "AGENT_SESSION_DIR": "",
            "AGENT_THINKING_PARAM_STYLE": "invalid_style",
        }
    )

    try:
        args = _parse_with_args([])
        options = runtime_options_from_args(args)

        assert options.show_llm_response is False
        assert options.stream is False
        assert options.thinking_mode == "auto"
        assert options.reasoning_effort == "none"
        assert options.thinking_capability == "auto"
        assert options.reasoning_preview_chars == 200
        assert options.save_session is False
        assert str(options.session_dir) == "sessions"
        assert options.thinking_param_style == "auto"
    finally:
        _restore_env(env_backup)

    print("PASS: test_invalid_env_falls_back_to_defaults")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_cli_overrides_env,
        test_env_parsing_without_cli,
        test_invalid_env_falls_back_to_defaults,
    ]) else 1)
