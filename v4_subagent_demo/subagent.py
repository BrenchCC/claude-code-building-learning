import os
import sys
import json
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.llm_call import build_assistant_message, call_chat_completion
from utils.reasoning_renderer import ReasoningRenderer
from utils.runtime_config import RuntimeOptions, add_runtime_args, runtime_options_from_args
from utils.session_store import SessionStore
from utils.thinking_policy import ThinkingPolicyState, build_thinking_params, resolve_thinking_policy
from utils.trace_logger import TraceLogger

logger = logging.getLogger("V4-Subagent")

SYSTEM_PROMPT_PATH = "prompts/v4_subagent.md"
INITIAL_REMINDER = "<reminder>Use todo_write for multi-step tasks.</reminder>"
NAG_REMINDER = "<reminder>10+ turns without todo update. Please update todos via todo_write.</reminder>"
MAX_MAIN_ROUNDS = 40
MAX_SUBAGENT_ROUNDS = 30

load_dotenv()

WORKSPACE = Path.cwd()
MODEL = os.getenv("LLM_MODEL")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)


AGENT_TYPE_REGISTRY = {
    "explore": {
        "description": "Read-only subagent for searching files and understanding code.",
        "tools": ["bash", "read_file"],
        "system_prompt": "You are an exploration subagent. Search and analyze, but never modify files. Return a concise summary.",
    },
    "code": {
        "description": "Implementation subagent with full tool access.",
        "tools": ["*"],
        "system_prompt": "You are a coding subagent. You have full access to implement changes efficiently in the codebase.",
    },
    "plan": {
        "description": "Read-only planning subagent for strategy and sequencing.",
        "tools": ["bash", "read_file"],
        "system_prompt": "You are a planning subagent. Analyze the codebase and output a numbered implementation plan. Do NOT make changes.",
    },
}


def get_agent_descriptions() -> str:
    """
    Build a bullet list describing all available agent types.
    """
    return "\n".join(
        f"- {agent_type}: {config['description']}"
        for agent_type, config in AGENT_TYPE_REGISTRY.items()
    )


class TodoManager:
    """
    Manage todo items with strict validation.
    """

    def __init__(self):
        self.items = []

    def update(self, items: List[Dict]) -> str:
        """
        Validate and replace the full todo list.

        Parameters:
            items: Full todo list payload from the model.
        """
        validated_items = []
        in_progress_count = 0

        for index, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).strip().lower()
            active_form = str(item.get("activeForm", "")).strip()

            if not content:
                raise ValueError(f"Item {index} is missing content.")
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(
                    f"Item {index} has invalid status '{status}'. "
                    "Must be pending|in_progress|completed."
                )
            if not active_form:
                raise ValueError(f"Item {index} is missing activeForm.")

            if status == "in_progress":
                in_progress_count += 1

            validated_items.append(
                {
                    "content": content,
                    "status": status,
                    "activeForm": active_form,
                }
            )

        if len(validated_items) > 20:
            raise ValueError("Too many todo items. Maximum allowed is 20.")
        if in_progress_count > 1:
            raise ValueError("Only one todo item can be in_progress at a time.")

        self.items = validated_items
        return self.render()

    def render(self) -> str:
        """
        Render todo items to a compact status view.
        """
        if not self.items:
            return "No TODO items."

        lines = []
        for item in self.items:
            if item["status"] == "completed":
                mark = "[✅]"
            elif item["status"] == "in_progress":
                mark = "[>]"
            else:
                mark = "[ ]"
            lines.append(f"{mark} {item['content']}")

        completed_count = sum(
            1 for item in self.items if item["status"] == "completed"
        )
        lines.append(f"Progress: {completed_count}/{len(self.items)} completed.")
        return "\n".join(lines)


TODO_MANAGER = TodoManager()

with open(SYSTEM_PROMPT_PATH, "r", encoding = "utf-8") as file:
    SYSTEM_PROMPT = file.read()
SYSTEM_PROMPT = SYSTEM_PROMPT.replace(
    "{get_agent_descriptions()}",
    get_agent_descriptions(),
)
SYSTEM_PROMPT = SYSTEM_PROMPT.format(workspace = WORKSPACE)
SYSTEM_PROMPT += (
    "\n\nTool naming note:\n"
    "- The todo tool function name is `todo_write`.\n"
    "- Prefer Task only from the main agent."
)


BASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file content with optional max_lines limit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write full content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace text in a file using exact old/new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_content": {"type": "string"},
                    "new_content": {"type": "string"},
                },
                "required": ["file_path", "old_content", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "Update complete todo list. Each item requires content, status, activeForm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string"},
                                "activeForm": {"type": "string"},
                            },
                            "required": ["content", "status", "activeForm"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
]


TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "Task",
        "description": f"""Spawn a subagent for focused work in isolated context.

Agent types:
{get_agent_descriptions()}""",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_type": {"type": "string"},
                "task_description": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": ["agent_type", "task_description", "prompt"],
        },
    },
}

TOOLS = BASE_TOOLS + [TASK_TOOL]


def get_tool_for_agent(agent_type: str) -> List[Dict]:
    """
    Get tool list for an agent type.

    Parameters:
        agent_type: The subagent type in AGENT_TYPE_REGISTRY.
    """
    config = AGENT_TYPE_REGISTRY.get(agent_type)
    if not config:
        raise ValueError(f"Unknown agent type: {agent_type}")

    allowed_tool_names = config["tools"]
    if "*" in allowed_tool_names:
        return [
            tool for tool in TOOLS
            if tool.get("function", {}).get("name") != "Task"
        ]

    selected_tools = []
    for tool in TOOLS:
        tool_name = tool.get("function", {}).get("name")
        if tool_name in allowed_tool_names:
            selected_tools.append(tool)
    return selected_tools


# Tool implementations
def bash(command: str) -> dict:
    """
    Execute shell command.

    Parameters:
        command: Command string to run.
    """
    try:
        result = subprocess.run(
            command,
            shell = True,
            cwd = WORKSPACE,
            capture_output = True,
            text = True,
            timeout = 300,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "(timeout after 300s)",
            "returncode": 124,
        }


def read_file(file_path: str, max_lines: Optional[int] = 1000) -> dict:
    """
    Read text content from a file.

    Parameters:
        file_path: Path of file to read.
        max_lines: Maximum lines to return. Use None for all.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    with path.open("r", encoding = "utf-8", errors = "replace") as file:
        if max_lines is None:
            content = file.read()
        else:
            content = "".join(file.readline() for _ in range(max_lines))
    return {"content": content}


def write_file(file_path: str, content: str) -> dict:
    """
    Write full text content to file.

    Parameters:
        file_path: Target file path.
        content: File content to write.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text(content, encoding = "utf-8")
    return {"status": "ok"}


def edit_file(file_path: str, old_content: str, new_content: str) -> dict:
    """
    Replace old text with new text in a file.

    Parameters:
        file_path: Target file path.
        old_content: Exact source text to replace.
        new_content: Replacement text.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    text = path.read_text(encoding = "utf-8", errors = "replace")
    if old_content not in text:
        return {"status": "not_found"}
    backup_path = path.with_suffix(path.suffix + ".bak")
    backup_path.write_text(text, encoding = "utf-8")
    path.write_text(text.replace(old_content, new_content), encoding = "utf-8")
    return {"status": "ok", "backup_path": str(backup_path)}


def todo_write(items: List[Dict]) -> dict:
    """
    Update todo list via TodoManager.

    Parameters:
        items: Full todo list payload.
    """
    try:
        rendered = TODO_MANAGER.update(items)
        return {"content": rendered}
    except ValueError as exc:
        return {"error": str(exc)}


def _parse_tool_args(arguments: str) -> Dict:
    """
    Parse tool call arguments JSON robustly.

    Parameters:
        arguments: JSON string from function-call payload.
    """
    if not arguments:
        return {}

    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        cleaned = "".join(ch for ch in arguments if ch >= " " or ch in "\t\n\r")
        try:
            return json.loads(cleaned, strict = False)
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse tool arguments: {exc}")
            return {}


def _assistant_turns_since_todo(history: List[Dict]) -> int:
    """
    Count assistant turns since the last todo_write tool call.

    Parameters:
        history: Full message history.
    """
    turns = 0
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            if tool_call.get("function", {}).get("name") == "todo_write":
                return turns
        turns += 1
    return turns


def _safe_call_tool(
    tool_name: str,
    args: Dict,
    runtime_options: Optional[RuntimeOptions] = None,
    trace_logger: Optional[TraceLogger] = None,
    session_store: Optional[SessionStore] = None,
    thinking_policy: Optional[ThinkingPolicyState] = None,
    interactive: bool = True,
) -> Tuple[Dict, Optional[str]]:
    """
    Execute a tool call with exception protection.

    Parameters:
        tool_name: Tool function name.
        args: Parsed tool argument dict.
    """
    try:
        return (
            _execute_tool_call(
                tool_name = tool_name,
                args = args,
                runtime_options = runtime_options,
                trace_logger = trace_logger,
                session_store = session_store,
                thinking_policy = thinking_policy,
                interactive = interactive,
            ),
            None,
        )
    except TypeError as exc:
        return {}, f"Tool '{tool_name}' argument error: {exc}"
    except Exception as exc:
        return {}, f"Tool '{tool_name}' runtime error: {exc}"


def run_task(
    description: str,
    prompt: str,
    agent_type: str,
    runtime_options: Optional[RuntimeOptions] = None,
    trace_logger: Optional[TraceLogger] = None,
    session_store: Optional[SessionStore] = None,
    thinking_policy: Optional[ThinkingPolicyState] = None,
) -> str:
    """
    Spawn and run a subagent in isolated context.

    Parameters:
        description: Human-readable subtask description.
        prompt: Prompt sent to the subagent.
        agent_type: Subagent type key (explore|code|plan).
        runtime_options: Runtime feature switches.
        trace_logger: Optional per-turn trace logger.
        session_store: Optional session persistence store.
        thinking_policy: Resolved thinking policy shared with parent loop.
    """
    config = AGENT_TYPE_REGISTRY.get(agent_type)
    if not config:
        return f"Error: Unknown agent type '{agent_type}'"

    options = runtime_options or RuntimeOptions()
    tracer = trace_logger or TraceLogger(enabled = options.show_llm_response)
    session = session_store or SessionStore(
        enabled = options.save_session,
        model = MODEL,
        session_dir = options.session_dir,
        runtime_options = options.as_dict(),
    )
    policy = thinking_policy or resolve_thinking_policy(
        client = LLM_SERVER,
        model = MODEL,
        capability_setting = options.thinking_capability,
        param_style_setting = options.thinking_param_style,
    )
    renderer = ReasoningRenderer(preview_chars = options.reasoning_preview_chars)
    show_reasoning = options.thinking_mode != "off"
    sub_actor = f"subagent:{agent_type}"

    sub_tools = get_tool_for_agent(agent_type)
    sub_messages = [{"role": "user", "content": prompt}]

    sub_system_prompt = (
        f"You are a {agent_type} subagent at {WORKSPACE}.\n\n"
        f"{config['system_prompt']}\n\n"
        "Complete the task and return a clear, concise summary."
    )

    print(f"  [{agent_type}] {description}")
    start_time = time.time()
    tool_count = 0

    for _ in range(MAX_SUBAGENT_ROUNDS):
        renderer.reset_turn()

        def _on_content_chunk(chunk: str) -> None:
            if not options.stream or not chunk:
                return
            sys.stdout.write(chunk)
            sys.stdout.flush()

        def _on_reasoning_chunk(chunk: str) -> None:
            if not options.stream or not show_reasoning:
                return
            renderer.handle_stream_chunk(chunk)

        result = call_chat_completion(
            client = LLM_SERVER,
            model = MODEL,
            messages = [{"role": "system", "content": sub_system_prompt}] + sub_messages,
            tools = sub_tools,
            max_tokens = 8192,
            stream = options.stream,
            thinking_params = build_thinking_params(
                policy = policy,
                thinking_mode = options.thinking_mode,
                reasoning_effort = options.reasoning_effort,
            ),
            on_content_chunk = _on_content_chunk,
            on_reasoning_chunk = _on_reasoning_chunk,
        )

        if options.stream and result.assistant_content:
            sys.stdout.write("\n")
            sys.stdout.flush()

        rendered_reasoning = result.assistant_reasoning if show_reasoning else ""
        renderer.finalize_turn(
            full_reasoning = rendered_reasoning,
            stream_mode = options.stream,
            allow_expand_prompt = False,
            interactive = False,
        )

        assistant_message = build_assistant_message(result)
        sub_messages.append(assistant_message)

        tracer.log_turn(
            actor = sub_actor,
            assistant_content = result.assistant_content,
            tool_calls = result.tool_calls,
            assistant_reasoning = rendered_reasoning,
        )
        session.record_assistant(
            actor = sub_actor,
            content = result.assistant_content,
            reasoning = rendered_reasoning,
            tool_calls = result.tool_calls,
            raw_metadata = result.raw_metadata,
        )

        if not result.tool_calls:
            elapsed = time.time() - start_time
            print(f"  [{agent_type}] {description} - done ({tool_count} tools, {elapsed:.1f}s)")
            return result.assistant_content or "(subagent returned no text)"

        tool_results = []
        for tool_call in result.tool_calls:
            function_block = tool_call.get("function") or {}
            tool_name = function_block.get("name")
            args = _parse_tool_args(function_block.get("arguments"))
            output, error = _safe_call_tool(
                tool_name = tool_name,
                args = args,
                runtime_options = options,
                trace_logger = tracer,
                session_store = session,
                thinking_policy = policy,
                interactive = False,
            )
            if error:
                output = {"error": error}

            tool_count += 1
            elapsed = time.time() - start_time
            sys.stdout.write(
                f"\r  [{agent_type}] {description} ... {tool_count} tools, {elapsed:.1f}s"
            )
            sys.stdout.flush()

            session.record_tool(
                actor = sub_actor,
                tool_name = tool_name or "unknown",
                arguments = args,
                output = output,
            )

            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": json.dumps(output, ensure_ascii = False)[:50000],
                }
            )

        sub_messages.extend(tool_results)

    return (
        f"Subagent stopped after reaching max rounds ({MAX_SUBAGENT_ROUNDS}). "
        f"Last task: {description}"
    )


def _execute_tool_call(
    tool_name: str,
    args: Dict,
    runtime_options: Optional[RuntimeOptions] = None,
    trace_logger: Optional[TraceLogger] = None,
    session_store: Optional[SessionStore] = None,
    thinking_policy: Optional[ThinkingPolicyState] = None,
    interactive: bool = True,
) -> Dict:
    """
    Execute a tool by name and return a JSON-serializable dict.

    Parameters:
        tool_name: Tool function name.
        args: Parsed tool argument dict.
    """
    if tool_name == "bash":
        cmd = args.get("command", "")
        print(f"\033[33m$ {cmd}\033[0m")
        output = bash(**args)
        combined_output = (output.get("stdout", "") or "") + (output.get("stderr", "") or "")
        print(combined_output or "(empty)")
        return output

    if tool_name == "read_file":
        return read_file(**args)
    if tool_name == "write_file":
        return write_file(**args)
    if tool_name == "edit_file":
        return edit_file(**args)
    if tool_name == "todo_write":
        output = todo_write(**args)
        if output.get("content"):
            print("\033[95mTodo List Updated:\033[0m")
            print(output["content"])
        return output
    if tool_name == "Task":
        description = args.get("task_description", "").strip()
        prompt = args.get("prompt", "").strip() or description
        agent_type = args.get("agent_type", "").strip()
        if not description:
            return {"error": "Task requires non-empty task_description."}
        if not agent_type:
            return {"error": "Task requires non-empty agent_type."}
        summary = run_task(
            description = description,
            prompt = prompt,
            agent_type = agent_type,
            runtime_options = runtime_options,
            trace_logger = trace_logger,
            session_store = session_store,
            thinking_policy = thinking_policy,
        )
        return {"content": summary}

    return {"error": f"Unknown tool: {tool_name}"}


def chat(
    prompt: Optional[str] = None,
    history: Optional[List[Dict]] = None,
    runtime_options: Optional[RuntimeOptions] = None,
    trace_logger: Optional[TraceLogger] = None,
    session_store: Optional[SessionStore] = None,
    actor: str = "main",
    interactive: bool = True,
) -> str:
    """
    Main agent loop with tool-calling and subagent orchestration.

    Parameters:
        prompt: User input string.
        history: Existing message history for multi-turn mode.
        runtime_options: Runtime feature switches.
        trace_logger: Optional per-turn trace logger.
        session_store: Optional session persistence store.
        actor: Actor label for trace/session records.
        interactive: Whether to allow interactive reasoning expansion prompt.
    """
    options = runtime_options or RuntimeOptions()
    tracer = trace_logger or TraceLogger(enabled = options.show_llm_response)
    session = session_store or SessionStore(
        enabled = options.save_session,
        model = MODEL,
        session_dir = options.session_dir,
        runtime_options = options.as_dict(),
    )
    renderer = ReasoningRenderer(preview_chars = options.reasoning_preview_chars)
    show_reasoning = options.thinking_mode != "off"
    thinking_policy = resolve_thinking_policy(
        client = LLM_SERVER,
        model = MODEL,
        capability_setting = options.thinking_capability,
        param_style_setting = options.thinking_param_style,
    )

    if history is None:
        history = []
    if prompt:
        history.append({"role": "user", "content": prompt})

    for _ in range(MAX_MAIN_ROUNDS):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if len(history) <= 1:
            messages.append({"role": "system", "content": INITIAL_REMINDER})
        elif _assistant_turns_since_todo(history) >= 10:
            messages.append({"role": "system", "content": NAG_REMINDER})

        messages.extend(history)

        renderer.reset_turn()

        def _on_content_chunk(chunk: str) -> None:
            if not options.stream or not chunk:
                return
            sys.stdout.write(chunk)
            sys.stdout.flush()

        def _on_reasoning_chunk(chunk: str) -> None:
            if not options.stream or not show_reasoning:
                return
            renderer.handle_stream_chunk(chunk)

        result = call_chat_completion(
            client = LLM_SERVER,
            model = MODEL,
            messages = messages,
            tools = TOOLS,
            max_tokens = 8192,
            stream = options.stream,
            thinking_params = build_thinking_params(
                policy = thinking_policy,
                thinking_mode = options.thinking_mode,
                reasoning_effort = options.reasoning_effort,
            ),
            on_content_chunk = _on_content_chunk,
            on_reasoning_chunk = _on_reasoning_chunk,
        )

        if options.stream and result.assistant_content:
            sys.stdout.write("\n")
            sys.stdout.flush()

        rendered_reasoning = result.assistant_reasoning if show_reasoning else ""
        renderer.finalize_turn(
            full_reasoning = rendered_reasoning,
            stream_mode = options.stream,
            allow_expand_prompt = not result.tool_calls,
            interactive = interactive,
        )

        assistant_message = build_assistant_message(result)

        history.append(assistant_message)

        tracer.log_turn(
            actor = actor,
            assistant_content = result.assistant_content,
            tool_calls = result.tool_calls,
            assistant_reasoning = rendered_reasoning,
        )
        session.record_assistant(
            actor = actor,
            content = result.assistant_content,
            reasoning = rendered_reasoning,
            tool_calls = result.tool_calls,
            raw_metadata = result.raw_metadata,
        )

        if not result.tool_calls:
            return result.assistant_content or ""

        tool_results = []
        for tool_call in result.tool_calls:
            function_block = tool_call.get("function") or {}
            tool_name = function_block.get("name")
            args = _parse_tool_args(function_block.get("arguments"))
            output, error = _safe_call_tool(
                tool_name = tool_name,
                args = args,
                runtime_options = options,
                trace_logger = tracer,
                session_store = session,
                thinking_policy = thinking_policy,
                interactive = interactive,
            )
            if error:
                output = {"error": error}
            session.record_tool(
                actor = actor,
                tool_name = tool_name or "unknown",
                arguments = args,
                output = output,
            )
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": json.dumps(output, ensure_ascii = False)[:50000],
                }
            )

        history.extend(tool_results)

    return (
        f"Stopped after reaching max rounds ({MAX_MAIN_ROUNDS}). "
        "The conversation may be stuck in repeated tool calls."
    )


def parse_args():
    """
    Parse command line arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description = "Subagent demo with TodoWrite and Task tools."
    )
    parser.add_argument(
        "prompt",
        nargs = "?",
        help = "User prompt for single-shot mode",
    )
    add_runtime_args(parser)

    args = parser.parse_args()
    args.runtime_options = runtime_options_from_args(args)
    return args


def main() -> int:
    """
    CLI entrypoint for single-shot and interactive modes.
    """
    args = parse_args()
    runtime_options = args.runtime_options

    logging.basicConfig(
        level = logging.INFO,
        format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers = [logging.StreamHandler()],
    )

    tracer = TraceLogger(enabled = runtime_options.show_llm_response, logger = logger)
    session = SessionStore(
        enabled = runtime_options.save_session,
        model = MODEL,
        session_dir = runtime_options.session_dir,
        runtime_options = runtime_options.as_dict(),
    )

    if args.prompt:
        logger.info("=" * 80)
        logger.info("Starting Subagent Demo in single-shot mode")
        logger.info("=" * 80)
        try:
            result = chat(
                prompt = args.prompt,
                runtime_options = runtime_options,
                trace_logger = tracer,
                session_store = session,
                interactive = sys.stdin.isatty(),
            )
            logger.info("-" * 60)
            logger.info("Final Response:")
            logger.info("-" * 60)
            if not runtime_options.stream:
                print(result)
        except Exception as exc:
            logger.error(f"Error: {exc}")
            return 1
        if session.get_path():
            logger.info(f"Session saved: {session.get_path()}")
        return 0

    logger.info("=" * 80)
    logger.info("Starting Subagent Demo in interactive mode")
    logger.info("=" * 80)
    logger.info("Type 'exit' or 'quit' to end the conversation.")
    logger.info("-" * 60)

    history = []
    try:
        while True:
            user_prompt = input("\033[94mUser:\033[0m ").strip()
            if user_prompt.lower() in {"exit", "quit"}:
                logger.info("Conversation ended.")
                break
            if not user_prompt:
                continue
            result = chat(
                prompt = user_prompt,
                history = history,
                runtime_options = runtime_options,
                trace_logger = tracer,
                session_store = session,
                interactive = True,
            )
            if not runtime_options.stream:
                print(f"\033[92mAssistant:\033[0m {result}")
    except KeyboardInterrupt:
        logger.info("Conversation interrupted.")
    except Exception as exc:
        logger.error(f"Error: {exc}")
        return 1

    if session.get_path():
        logger.info(f"Session saved: {session.get_path()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
