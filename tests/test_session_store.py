"""Unit tests for session JSONL persistence."""

import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import run_tests
from utils.session_store import SessionStore


def test_filename_rule_and_creation():
    """Session filename should follow sanitized_model_timestamp.jsonl pattern."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SessionStore(
            enabled = True,
            model = "my/model:v1",
            session_dir = tmpdir,
            runtime_options = {"stream": False},
        )

        path = store.get_path()
        assert path is not None, "Expected a session file path"
        assert path.exists(), "Session file should be created immediately"
        pattern = r"^my_model_v1_\d{8}_\d{6}\.jsonl$"
        assert re.match(pattern, path.name), f"Unexpected session filename: {path.name}"

    print("PASS: test_filename_rule_and_creation")
    return True


def test_jsonl_structure_completeness():
    """Session file should contain meta + assistant + tool events with full payload."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SessionStore(
            enabled = True,
            model = "demo-model",
            session_dir = tmpdir,
            runtime_options = {"stream": True, "save_session": True},
        )

        store.record_assistant(
            actor = "main",
            content = "assistant reply",
            reasoning = "full reasoning",
            tool_calls = [{"id": "1", "function": {"name": "bash", "arguments": "{}"}}],
            raw_metadata = {"response_id": "abc"},
        )
        store.record_tool(
            actor = "main",
            tool_name = "bash",
            arguments = {"command": "echo hi"},
            output = {"stdout": "hi"},
        )

        with store.get_path().open("r", encoding = "utf-8") as file:
            lines = [json.loads(line) for line in file]

        assert len(lines) == 3, f"Expected 3 JSONL lines, got {len(lines)}"
        assert lines[0]["event"] == "meta"
        assert lines[0]["runtime_options"]["stream"] is True
        assert lines[1]["event"] == "assistant"
        assert lines[1]["reasoning"] == "full reasoning"
        assert lines[2]["event"] == "tool"
        assert lines[2]["tool_name"] == "bash"

    print("PASS: test_jsonl_structure_completeness")
    return True


def test_disabled_mode_no_file():
    """Disabled session mode should not create output file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SessionStore(
            enabled = False,
            model = "demo-model",
            session_dir = tmpdir,
            runtime_options = {},
        )
        assert store.get_path() is None

    print("PASS: test_disabled_mode_no_file")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_filename_rule_and_creation,
        test_jsonl_structure_completeness,
        test_disabled_mode_no_file,
    ]) else 1)
