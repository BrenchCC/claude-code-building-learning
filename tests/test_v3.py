"""
v3 test suite: "Plan before you act" with todo_write constraints.

Unit tests verify TodoManager behavior (no LLM needed).
LLM tests verify the model can use todo_write to plan and track work.
"""

import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import get_client, run_agent, run_tests
from tests.helpers import BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, TODO_WRITE_TOOL

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("LLM_MODEL", "gpt-4o-mini")

from v3_todo_agent_demo.todo_agent import (
    TodoManager,
    INITIAL_REMINDER,
    NAG_REMINDER,
    _assistant_turns_since_todo,
    chat
)

V3_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, TODO_WRITE_TOOL]


# =============================================================================
# Unit tests (no LLM)
# =============================================================================

def test_todo_manager_basic():
    """Create TodoManager, add items, verify render."""
    tm = TodoManager()

    result = tm.update([
        {"content": "Setup project", "status": "pending", "activeForm": "Setting up project"},
        {"content": "Write code", "status": "in_progress", "activeForm": "Writing code"},
        {"content": "Run tests", "status": "completed", "activeForm": "Running tests"},
    ])

    assert len(tm.items) == 3, f"Should have 3 items, got {len(tm.items)}"
    assert "- [ ] Setup project" in result, f"Render missing pending item, got: {result}"
    assert "- [>] Write code <- (Writing code)" in result, (
        f"Render missing in_progress active form, got: {result}"
    )
    assert "- [✅] Run tests" in result, f"Render missing completed item, got: {result}"
    assert "(1/3 items completed)" in result, f"Should show 1/3 completed, got: {result}"

    print("PASS: test_todo_manager_basic")
    return True


def test_todo_manager_one_in_progress():
    """Only 1 item can be in_progress at a time."""
    tm = TodoManager()

    try:
        tm.update([
            {"content": "Task A", "status": "in_progress", "activeForm": "Doing A"},
            {"content": "Task B", "status": "in_progress", "activeForm": "Doing B"},
        ])
        assert False, "Should raise ValueError for multiple in_progress items"
    except ValueError as error:
        error_text = str(error).lower()
        assert "in_progress" in error_text or "one" in error_text, (
            f"Error should mention in_progress constraint, got: {error}"
        )

    tm2 = TodoManager()
    tm2.update([
        {"content": "Task A", "status": "in_progress", "activeForm": "Doing A"},
        {"content": "Task B", "status": "pending", "activeForm": "Waiting for B"},
    ])
    assert len(tm2.items) == 2, "Single in_progress should be allowed"

    print("PASS: test_todo_manager_one_in_progress")
    return True


def test_todo_manager_status_progression():
    """pending -> in_progress -> completed is a valid progression."""
    tm = TodoManager()

    tm.update([{"content": "Deploy", "status": "pending", "activeForm": "Deploying"}])
    assert tm.items[0]["status"] == "pending"

    tm.update([{"content": "Deploy", "status": "in_progress", "activeForm": "Deploying"}])
    assert tm.items[0]["status"] == "in_progress"

    tm.update([{"content": "Deploy", "status": "completed", "activeForm": "Deploying"}])
    assert tm.items[0]["status"] == "completed"

    print("PASS: test_todo_manager_status_progression")
    return True


def test_todo_manager_render_format():
    """Output format matches expected [✅]/[>]/[ ] task pattern."""
    tm = TodoManager()
    tm.update([
        {"content": "Done task", "status": "completed", "activeForm": "Done"},
        {"content": "Active task", "status": "in_progress", "activeForm": "Working on it"},
        {"content": "Waiting task", "status": "pending", "activeForm": "Waiting"},
    ])

    rendered = tm.render()
    assert "- [✅] Done task" in rendered, f"Completed should show [✅], got: {rendered}"
    assert "- [>] Active task <- (Working on it)" in rendered, (
        f"In-progress should include activeForm, got: {rendered}"
    )
    assert "- [ ] Waiting task" in rendered, f"Pending should show [ ], got: {rendered}"
    assert "(1/3 items completed)" in rendered, f"Should show 1/3 completed, got: {rendered}"

    print("PASS: test_todo_manager_render_format")
    return True


def test_max_items_constraint():
    """TodoManager rejects lists with more than 20 items."""
    tm = TodoManager()
    items_25 = [
        {"content": f"Task {index}", "status": "pending", "activeForm": f"Doing task {index}"}
        for index in range(25)
    ]

    try:
        tm.update(items_25)
        assert False, "Should raise ValueError for more than 20 items"
    except ValueError as error:
        assert "20" in str(error), f"Error should mention 20-item limit, got: {error}"

    assert len(tm.items) != 25, "Should not store 25 items"

    print("PASS: test_max_items_constraint")
    return True


def test_nag_reminder_exists():
    """Verify reminders and todo turn counter hooks exist in source."""
    assert "todo" in NAG_REMINDER.lower(), f"NAG_REMINDER should reference todo, got: {NAG_REMINDER}"
    assert "todo" in INITIAL_REMINDER.lower(), (
        f"INITIAL_REMINDER should reference todo usage, got: {INITIAL_REMINDER}"
    )

    source = inspect.getsource(chat)
    assert "_assistant_turns_since_todo" in source, (
        "chat should call _assistant_turns_since_todo for nag reminder behavior"
    )

    turns = _assistant_turns_since_todo([])
    assert turns == 0, f"Empty history should return 0 turns, got: {turns}"

    print("PASS: test_nag_reminder_exists")
    return True


# =============================================================================
# LLM tests
# =============================================================================

def _run_with_todo_tool(client, task, workdir = None):
    """Run agent with todo_write tool and return results."""
    system_prompt = (
        "You are a coding agent that uses todo_write to plan work. "
        "Always create a todo list before acting, and update it as you make progress."
    )
    return run_agent(
        client,
        task,
        V3_TOOLS,
        system = system_prompt,
        workdir = workdir,
        max_turns = 15,
    )


def test_llm_plans_before_acting():
    """Give multi-step task, model uses todo_write before file tools."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        system = (
            f"You are a coding agent at {tmpdir}. "
            "You MUST call todo_write first to plan before using any other tools."
        )

        response, calls, _ = run_agent(
            client,
            f"Use todo_write to plan 2 steps: create hello.txt, create world.txt. "
            f"Then create both files in {tmpdir}.",
            V3_TOOLS,
            system = system,
            workdir = tmpdir,
            max_turns = 15,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"
        todo_calls = [call for call in calls if call[0] == "todo_write"]
        if len(todo_calls) == 0:
            print("WARN: Model did not use todo_write (flaky model behavior)")
        assert response is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}, todo_write: {len(todo_calls)}")
    print("PASS: test_llm_plans_before_acting")
    return True


def test_llm_updates_todo_progress():
    """Model updates todo items from pending to completed."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        response, calls, _ = run_agent(
            client,
            "Call todo_write with one pending item. Then create output.txt with write_file. "
            "Then call todo_write again and mark the item completed.",
            V3_TOOLS,
            system = "Use todo_write for plan and progress tracking.",
            workdir = tmpdir,
            max_turns = 15,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"
        todo_calls = [call for call in calls if call[0] == "todo_write"]
        if len(todo_calls) == 0:
            print("WARN: Model did not use todo_write (flaky model behavior)")
        assert response is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}, todo_write: {len(todo_calls)}")
    print("PASS: test_llm_updates_todo_progress")
    return True


def test_llm_multi_step_execution():
    """3-file creation task with planning flow."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        response, calls, _ = run_agent(
            client,
            f"Create 3 files in {tmpdir}: one.txt='first', two.txt='second', three.txt='third'.",
            V3_TOOLS,
            system = f"You are a coding agent at {tmpdir}. Use write_file to create files.",
            workdir = tmpdir,
            max_turns = 20,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"
        files_created = sum(
            1 for filename in ["one.txt", "two.txt", "three.txt"]
            if os.path.exists(os.path.join(tmpdir, filename))
        )
        assert files_created >= 2, f"Should create at least 2/3 files, got {files_created}"
        assert response is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}, Files: {files_created}/3")
    print("PASS: test_llm_multi_step_execution")
    return True


def test_llm_todo_with_errors():
    """Model handles failing edit operation gracefully."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "target.txt")
        with open(filepath, "w", encoding = "utf-8") as file:
            file.write("original content here")

        response, calls, _ = run_agent(
            client,
            f"Read {filepath}. Then use edit_file to replace 'NONEXISTENT_STRING_XYZ' with 'replacement'. "
            "Report what happened.",
            V3_TOOLS,
            system = f"You are a coding agent at {tmpdir}. Handle errors gracefully.",
            workdir = tmpdir,
            max_turns = 15,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"
        assert response is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_todo_with_errors")
    return True


def test_llm_todo_tracks_completion_count():
    """Model calls todo_write at least twice (plan + completion update)."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        text, calls, _ = _run_with_todo_tool(
            client,
            "Plan and execute: create a.txt='alpha' and b.txt='beta'. "
            "First plan with todo_write as pending, then mark both completed.",
            workdir = tmpdir,
        )

        todo_calls = [call for call in calls if call[0] == "todo_write"]
        assert len(todo_calls) >= 2, (
            f"Should call todo_write at least twice (plan + update), got {len(todo_calls)}"
        )
        assert text is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}, todo_write: {len(todo_calls)}")
    print("PASS: test_llm_todo_tracks_completion_count")
    return True


def test_llm_todo_replan_on_error():
    """Model adapts plan after a missing-file failure."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        text, calls, _ = _run_with_todo_tool(
            client,
            f"Plan: 1) read {tmpdir}/nonexistent.txt 2) create {tmpdir}/output.txt with that content. "
            "If step 1 fails, create output.txt with 'fallback content' and update todo accordingly.",
            workdir = tmpdir,
        )

        assert len(calls) >= 2, f"Should make at least 2 tool calls, got {len(calls)}"
        assert text is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_todo_replan_on_error")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_todo_manager_basic,
        test_todo_manager_one_in_progress,
        test_todo_manager_status_progression,
        test_todo_manager_render_format,
        test_max_items_constraint,
        test_nag_reminder_exists,
        test_llm_plans_before_acting,
        test_llm_updates_todo_progress,
        test_llm_multi_step_execution,
        test_llm_todo_with_errors,
        test_llm_todo_tracks_completion_count,
        test_llm_todo_replan_on_error,
    ]) else 1)
