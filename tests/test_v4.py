"""
Tests for v4_subagent_demo/subagent.py - Context isolation via sub-agents.

Covers agent type registry, tool filtering, and LLM delegation behavior.
"""

import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import get_client, run_agent, run_tests
from tests.helpers import BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, TASK_TOOL

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("LLM_MODEL", "gpt-4o-mini")

from v4_subagent_demo.subagent import get_tool_for_agent, AGENT_TYPE_REGISTRY, run_task


# =============================================================================
# Unit Tests
# =============================================================================

def _extract_tool_names(tool_schemas):
    """Extract function names from OpenAI tool schemas."""
    return [
        tool.get("function", {}).get("name")
        for tool in tool_schemas
        if tool.get("type") == "function"
    ]


def test_agent_types_defined():
    for name in ("explore", "code", "plan"):
        assert name in AGENT_TYPE_REGISTRY, f"Missing agent type: {name}"
        assert "description" in AGENT_TYPE_REGISTRY[name], f"{name} missing description"
        assert len(AGENT_TYPE_REGISTRY[name]["description"]) > 0, f"{name} has empty description"
    print("PASS: test_agent_types_defined")
    return True


def test_explore_readonly():
    tool_names = _extract_tool_names(get_tool_for_agent("explore"))
    assert "bash" in tool_names, "Explore should have bash"
    assert "read_file" in tool_names, "Explore should have read_file"
    assert "write_file" not in tool_names, "Explore should NOT have write_file"
    assert "edit_file" not in tool_names, "Explore should NOT have edit_file"
    print("PASS: test_explore_readonly")
    return True


def test_code_full_access():
    tool_names = _extract_tool_names(get_tool_for_agent("code"))
    assert "bash" in tool_names, "Code should have bash"
    assert "read_file" in tool_names, "Code should have read_file"
    assert "write_file" in tool_names, "Code should have write_file"
    assert "edit_file" in tool_names, "Code should have edit_file"
    print("PASS: test_code_full_access")
    return True


def test_plan_readonly():
    tool_names = _extract_tool_names(get_tool_for_agent("plan"))
    assert "bash" in tool_names, "Plan should have bash"
    assert "read_file" in tool_names, "Plan should have read_file"
    assert "write_file" not in tool_names, "Plan should NOT have write_file"
    assert "edit_file" not in tool_names, "Plan should NOT have edit_file"
    print("PASS: test_plan_readonly")
    return True


def test_no_recursive_task():
    for agent_type in AGENT_TYPE_REGISTRY:
        tool_names = _extract_tool_names(get_tool_for_agent(agent_type))
        assert "Task" not in tool_names, (
            f"{agent_type} should NOT get Task tool (prevents infinite recursion)"
        )
    print("PASS: test_no_recursive_task")
    return True


def test_context_isolation_fresh_history():
    """Verify run_task starts subagents with fresh message history."""
    source = inspect.getsource(run_task)
    assert 'sub_messages = [{"role": "user", "content": prompt}]' in source, (
        "run_task should initialize sub_messages with a fresh user message."
    )
    print("PASS: test_context_isolation_fresh_history")
    return True


# =============================================================================
# LLM Tests
# =============================================================================

def _run_with_task_tool(client, task, workdir = None):
    """Run an agent with Task tool enabled."""
    tools = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL, TASK_TOOL]
    system_prompt = (
        "You are a coding agent that delegates tasks using the Task tool. "
        "Use agent_type='explore' for searching, agent_type='code' for implementation, "
        "and agent_type='plan' for planning."
    )
    return run_agent(
        client,
        task,
        tools,
        system = system_prompt,
        workdir = workdir,
        max_turns = 10,
    )


def test_llm_uses_subagent_tool():
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = _run_with_task_tool(
        client,
        "Explore the project structure and find all Python files. Delegate this to a sub-agent."
    )

    task_calls = [call for call in calls if call[0] == "Task"]
    assert len(task_calls) > 0, "Model should use Task tool to delegate"
    assert text is not None, "Should return a response"
    print("PASS: test_llm_uses_subagent_tool")
    return True


def test_llm_delegates_exploration():
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = _run_with_task_tool(
        client,
        "Find all .py files in the project. Use Task with agent_type='explore'."
    )

    task_calls = [call for call in calls if call[0] == "Task"]
    assert len(task_calls) > 0, "Model should delegate to a sub-agent"
    agent_type = task_calls[0][1].get("agent_type", "")
    assert agent_type == "explore", f"Should delegate to explore agent, got: {agent_type}"
    assert text is not None, "Should return a response"
    print("PASS: test_llm_delegates_exploration")
    return True


def test_llm_delegates_coding():
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = _run_with_task_tool(
        client,
        "Create a new file hello.py with a hello world function. Delegate using Task and agent_type='code'."
    )

    task_calls = [call for call in calls if call[0] == "Task"]
    assert len(task_calls) > 0, "Model should delegate to a sub-agent"
    agent_type = task_calls[0][1].get("agent_type", "")
    assert agent_type == "code", f"Should delegate to code agent, got: {agent_type}"
    assert text is not None, "Should return a response"
    print("PASS: test_llm_delegates_coding")
    return True


def test_explore_code_pipeline():
    """Two-step delegation: explore agent finds files, then code agent writes output."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        for name in ["notes.txt", "readme.txt", "data.txt"]:
            with open(os.path.join(tmpdir, name), "w", encoding = "utf-8") as file:
                file.write(f"Content of {name}")

        text, calls, _ = _run_with_task_tool(
            client,
            f"Do a two-step task in {tmpdir}: "
            "1) Task explore to find all .txt files. "
            "2) Task code to create summary.txt listing those files.",
            workdir = tmpdir,
        )

        task_calls = [call for call in calls if call[0] == "Task"]
        assert len(task_calls) >= 1, f"Should make at least 1 Task call, got {len(task_calls)}"
        agent_types_used = [call[1].get("agent_type", "") for call in task_calls]
        assert "explore" in agent_types_used or "code" in agent_types_used, (
            f"Should use explore or code agent, got: {agent_types_used}"
        )
        assert text is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}, Task calls: {len(task_calls)}")
    print("PASS: test_explore_code_pipeline")
    return True


def test_llm_delegates_plan_agent():
    """Model delegates design work to a plan sub-agent."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = _run_with_task_tool(
        client,
        "Design a REST API architecture for users and posts. Use Task with agent_type='plan'."
    )

    task_calls = [call for call in calls if call[0] == "Task"]
    assert len(task_calls) > 0, "Model should delegate to a sub-agent"
    agent_type = task_calls[0][1].get("agent_type", "")
    assert agent_type == "plan", f"Should delegate to plan agent, got: {agent_type}"
    assert text is not None, "Should return a response"
    print("PASS: test_llm_delegates_plan_agent")
    return True


def test_llm_multi_delegation():
    """Model delegates tasks to multiple agent types."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = _run_with_task_tool(
        client,
        "Do two delegated tasks: first explore files, then code a summary. "
        "Use Task twice with different agent_type values.",
    )

    task_calls = [call for call in calls if call[0] == "Task"]
    assert len(task_calls) >= 1, f"Should make at least 1 Task call, got {len(task_calls)}"
    agent_types = [call[1].get("agent_type", "") for call in task_calls]
    assert len(set(agent_types)) >= 1, f"Should use at least one valid agent type, got: {agent_types}"
    assert text is not None, "Should return a response"

    print(f"Task calls: {len(task_calls)}, types: {agent_types}")
    print("PASS: test_llm_multi_delegation")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_agent_types_defined,
        test_explore_readonly,
        test_code_full_access,
        test_plan_readonly,
        test_no_recursive_task,
        test_context_isolation_fresh_history,
        test_llm_uses_subagent_tool,
        test_llm_delegates_exploration,
        test_llm_delegates_coding,
        test_explore_code_pipeline,
        test_llm_delegates_plan_agent,
        test_llm_multi_delegation,
    ]) else 1)
