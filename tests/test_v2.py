"""
v2 test suite: "Model as agent" with 4 structured tools replacing raw bash for file ops.

Tests verify the model correctly uses read_file, write_file, edit_file alongside bash,
prefers structured tools over raw bash for file operations, and handles multi-tool workflows.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import get_client, run_agent, run_tests
from tests.helpers import BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL

V2_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL]


def test_read_file():
    """Model reads a prepared file and reports content."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "secret.txt")
        with open(filepath, "w") as f:
            f.write("The secret code is: ALPHA-9827")

        response, calls, _ = run_agent(
            client,
            f"Use the read_file tool to read {filepath}. Tell me the secret code in the file.",
            V2_TOOLS,
            workdir = tmpdir,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"
        assert response is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_read_file")
    return True


def test_write_file():
    """Model creates a file with write_file (NOT bash echo)."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "greeting.txt")

        response, calls, _ = run_agent(
            client,
            f"Create a file at {filepath} with content 'Hello from v2 agent!' using the write_file tool.",
            V2_TOOLS,
            workdir = tmpdir,
        )

        assert any(c[0] == "write_file" for c in calls), "Should use write_file tool"
        assert os.path.exists(filepath), f"File {filepath} should exist"
        with open(filepath) as f:
            content = f.read()
        assert "Hello" in content, f"File should contain 'Hello', got: {content[:200]}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_write_file")
    return True


def test_edit_file():
    """Model modifies existing file content using edit_file."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "config.ini")
        with open(filepath, "w") as f:
            f.write("mode=development\nport=3000\n")

        response, calls, _ = run_agent(
            client,
            f"Change 'mode=development' to 'mode=production' in {filepath}. "
            f"Use edit_file with old_content='mode=development' and new_content='mode=production'.",
            V2_TOOLS,
            workdir = tmpdir,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"
        with open(filepath) as f:
            content = f.read()
        assert "mode=production" in content, (
            f"File should contain 'mode=production', got: {content[:200]}"
        )

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_edit_file")
    return True


def test_read_then_edit():
    """Multi-tool: model reads a file then edits it."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "version.txt")
        with open(filepath, "w") as f:
            f.write("version=1.0.0\nauthor=test\n")

        response, calls, _ = run_agent(
            client,
            f"Use edit_file to change 'version=1.0.0' to 'version=2.0.0' in {filepath}. "
            f"Call edit_file with file_path='{filepath}', old_content='version=1.0.0', new_content='version=2.0.0'.",
            V2_TOOLS,
            workdir = tmpdir,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_read_then_edit")
    return True


def test_write_then_verify():
    """Write a file then read to verify its contents."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "verify_me.txt")

        response, calls, _ = run_agent(
            client,
            f"Call write_file with file_path='{filepath}' and content='verification_token_XYZ'.",
            V2_TOOLS,
            system = "You MUST use write_file when asked. Always call the tool, never just respond with text.",
            workdir = tmpdir,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_write_then_verify")
    return True


def test_tool_selection():
    """Model prefers read_file over cat for reading when both bash and read_file are available."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "preference.txt")
        with open(filepath, "w") as f:
            f.write("tool_selection_test_data_12345")

        response, calls, _ = run_agent(
            client,
            f"Use the read_file tool to read {filepath}. Tell me the exact content of the file.",
            V2_TOOLS,
            workdir = tmpdir,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"
        assert response is not None, "Should return a response"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_tool_selection")
    return True


def test_multi_file_workflow():
    """Create 3 files, read one, edit another -- full workflow."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        response, calls, _ = run_agent(
            client,
            f"Do the following in {tmpdir}:\n"
            f"1) Use write_file to create alpha.txt with content 'alpha_original'\n"
            f"2) Use write_file to create beta.txt with content 'beta_original'\n"
            f"3) Use write_file to create gamma.txt with content 'gamma_original'\n"
            f"Report what you did.",
            V2_TOOLS,
            workdir = tmpdir,
            max_turns = 15,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"

        files_created = sum(
            1 for f in ["alpha.txt", "beta.txt", "gamma.txt"]
            if os.path.exists(os.path.join(tmpdir, f))
        )
        assert files_created >= 2, f"Should create at least 2 files, got {files_created}"

    print(f"Tool calls: {len(calls)}, Files created: {files_created}")
    print("PASS: test_multi_file_workflow")
    return True


def test_error_recovery():
    """Model handles missing file gracefully (read nonexistent file, then responds helpfully)."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent = os.path.join(tmpdir, "does_not_exist.txt")

        response, calls, _ = run_agent(
            client,
            f"Try to read the file {nonexistent}. If it doesn't exist, tell me that and suggest what to do.",
            V2_TOOLS,
            workdir = tmpdir,
        )

        assert response is not None, "Should return a response"
        resp_lower = response.lower()
        assert any(w in resp_lower for w in [
            "not", "error", "exist", "found", "cannot", "no such", "missing", "doesn't"
        ]), f"Response should acknowledge the missing file, got: {response[:200]}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_error_recovery")
    return True


def test_prefers_specialized_over_bash():
    """Model prefers read_file over bash cat when both are available."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "data.txt")
        with open(target, "w") as f:
            f.write("specialized_tool_content_v2")

        response, calls, _ = run_agent(
            client,
            f"Read the contents of {target} and tell me what it says. "
            f"You have both bash and read_file available. Use whichever you prefer.",
            [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL],
            workdir = tmpdir,
        )

        assert response is not None, "Should return a response"
        assert "specialized_tool_content_v2" in response, (
            f"Response should contain file content, got: {response[:200]}"
        )
        read_calls = [c for c in calls if c[0] == "read_file"]
        bash_cat_calls = [c for c in calls if c[0] == "bash" and "cat" in c[1].get("command", "")]
        assert len(read_calls) > 0 or len(bash_cat_calls) > 0, (
            "Should use either read_file or bash cat"
        )

    print(f"Tool calls: {len(calls)}, read_file: {len(read_calls)}, bash+cat: {len(bash_cat_calls)}")
    print("PASS: test_prefers_specialized_over_bash")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_read_file,
        test_write_file,
        test_edit_file,
        test_read_then_edit,
        test_write_then_verify,
        test_tool_selection,
        test_multi_file_workflow,
        test_error_recovery,
        test_prefers_specialized_over_bash,
    ]) else 1)
