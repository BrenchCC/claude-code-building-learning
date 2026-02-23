"""
Tests for v6_compression_agent_demo/compression_agent.py - Compression + Agent class.

Focus on ContextManager behaviors and Agent tool execution without requiring LLM calls.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import run_tests

from v6_compression_agent_demo.compression_agent import (
    Agent,
    ContextManager,
    WORKSPACE,
    TODO_MANAGER,
)


def _make_big_text(size: int) -> str:
    return "x" * size


# =============================================================================
# Unit Tests
# =============================================================================


def test_context_manager_micro_compact_clears_old_tools():
    manager = ContextManager()

    big = _make_big_text(90000)
    messages = [
        {"role": "tool", "name": "read_file", "content": big},
        {"role": "tool", "name": "read_file", "content": big},
        {"role": "tool", "name": "read_file", "content": big},
        {"role": "tool", "name": "read_file", "content": big},
    ]

    result = manager.micro_compact(messages)

    assert result[0]["content"] == "[Old tool result content cleared]", (
        "Old tool result should be compacted when savings exceed threshold"
    )
    assert result[-1]["content"] == big, "Most recent tool result should be kept"

    print("PASS: test_context_manager_micro_compact_clears_old_tools")
    return True


def test_context_manager_handle_large_output():
    manager = ContextManager()

    oversized = _make_big_text(manager.MAX_OUTPUT_TOKENS * 5)
    result = manager.handle_large_output(oversized)

    assert "Saved to:" in result, "Expected handle_large_output to save oversized output"

    saved_path = None
    for line in result.splitlines():
        if line.startswith("Output too large") and "Saved to:" in line:
            saved_path = line.split("Saved to:", 1)[1].strip()
            break

    assert saved_path, "Expected to parse saved path from handle_large_output result"
    assert Path(saved_path).exists(), "Saved output file should exist"

    Path(saved_path).unlink(missing_ok = True)

    print("PASS: test_context_manager_handle_large_output")
    return True


def test_context_manager_restore_recent_files():
    manager = ContextManager()

    temp_path = WORKSPACE / "tests" / "_v6_restore_tmp.txt"
    temp_path.write_text("restore_me", encoding = "utf-8")

    messages = [
        {
            "role": "assistant",
            "content": [
                {"name": "read_file", "input": {"path": str(temp_path)}},
            ],
        }
    ]

    restored = manager.restore_recent_files(messages)
    assert len(restored) == 1, "Expected one restored file message"
    assert "restore_me" in restored[0]["content"], "Restored content should include file text"

    temp_path.unlink(missing_ok = True)

    print("PASS: test_context_manager_restore_recent_files")
    return True


def test_agent_todo_write_updates_state():
    agent = Agent()

    items = [
        {
            "content": "Do the thing",
            "status": "in_progress",
            "activeForm": "Doing the thing",
        }
    ]

    result = agent._execute_tool_call(
        tool_name = "todo_write",
        args = {"items": items},
        interactive = False,
    )

    assert "content" in result, "todo_write should return rendered todo content"
    assert len(TODO_MANAGER.items) == 1, "TodoManager should be updated"

    print("PASS: test_agent_todo_write_updates_state")
    return True


# =============================================================================
# Runner
# =============================================================================


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_context_manager_micro_compact_clears_old_tools,
        test_context_manager_handle_large_output,
        test_context_manager_restore_recent_files,
        test_agent_todo_write_updates_state,
    ]) else 1)
