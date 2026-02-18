import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.llm_call import build_assistant_message, call_chat_completion
from utils.reasoning_renderer import ReasoningRenderer
from utils.runtime_config import RuntimeOptions, add_runtime_args, runtime_options_from_args
from utils.session_store import SessionStore
from utils.thinking_policy import build_thinking_params, resolve_thinking_policy
from utils.trace_logger import TraceLogger


logger = logging.getLogger("V3-Todo-Agent")

SYSTEM_PROMPT_PATH = "prompts/v3_todo_agent.md"

load_dotenv()

WORKSPACE = Path.cwd()

MODEL = os.getenv("LLM_MODEL")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

# Define the TodoManager class to handle todo list operations   
class TodoManager:
    """
    Manages a structured task list with enforced constraints.
    Key features include:
    --------------------
    1. Max 20 items: Prevents the model from creating endless lists
    2. One in_progress: Forces focus - can only work on ONE thing at a time
    3. Required fields: Each item needs content, status, and activeForm

    The activeForm field deserves explanation:
    - It's the PRESENT TENSE form of what's happening
    - Shown when status is "in_progress"
    - Example: content="Add tests", activeForm="Adding unit tests..."

    This gives real-time visibility into what the agent is doing.
    """
    def __init__(self):
        self.items = []

    def render(self) -> str:
        """
        Render the todo list in a clear text format for the model.

        Example:
        1. [pending] Add tests
        2. [in_progress] Write documentation (Writing docs...)
        3. [completed] Refactor code
        (3/5 items completed)

        Returns:
            A string representation of the todo list.
        """
        if not self.items:
            logger.info("Todo list is currently empty.")
            return "Todo list is empty."
        lines = []
        for item in self.items:
            line = ""
            if item["status"] == "completed":
                line = f"- [✅] {item['content']}"
            elif item["status"] == "in_progress":
                line = f"- [>] {item['content']} <- ({item['activeForm']})"
            else:
                line = f"- [ ] {item['content']}"
            lines.append(line)
        
        completed_count = sum(1 for item in self.items if item["status"] == "completed")
        lines.append(f"({completed_count}/{len(self.items)} items completed)")

        return "\n".join(lines)



    def update(self, items: List[Dict]) -> str:
        """
        Validate and update todo list.

        The model sends a complete new list each time. We validate it,
        store it, and return a rendered view that the model will see.

        Validation Rules:
        - Each item must have: content, status, activeForm
        - Status must be: pending | in_progress | completed
        - Only ONE item can be in_progress at a time
        - Maximum 20 items allowed

        Returns:
            Rendered text view of the todo list
        """
        validated = []
        in_progess_count = 0

        for i, item in enumerate(items):
            # Extract and validate fields
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).strip().lower()
            active_form = str(item.get("activeForm", "")).strip()

            # Basic validation
            if not content:
                logger.warning(f"Item {i} missing content. Skipping.")
                raise ValueError(f"Item {i} is missing content. Content is required.")
            if status not in {"pending", "in_progress", "completed"}:
                logger.warning(f"Item {i} has invalid status '{status}'")
                raise ValueError(f"Item {i} has invalid status '{status}'. Must be 'pending', 'in_progress', or 'completed'.")
            if not active_form:
                logger.warning(f"Item {i} missing activeForm. activeForm is required.")
                raise ValueError(f"Item {i} is missing activeForm. activeForm is required.")
            
            if status == "in_progress":
                in_progess_count += 1

            validated.append({
                "content": content,
                "status": status,
                "activeForm": active_form
            })

        item_num = len(validated)
        if item_num > 20:
            logger.warning(f"Too many items: {item_num}. Maximum is 20.")
            raise ValueError(f"Too many items: {item_num}. Maximum allowed is 20.")
        
        if in_progess_count > 1:
            logger.warning(f"Multiple items marked as in_progress. Item {i} is invalid.")
            raise ValueError(f"Only one item can be in_progress at a time. Item {i} is invalid.")
            
        self.items = validated

        return self.render()

# =============================================================================
# Initialize a global instance of TodoManager to be used by the agent
# =============================================================================
Todo_Manager = TodoManager()

with open(SYSTEM_PROMPT_PATH, "r") as f:
    SYSTEM_PROMPT = f.read()
SYSTEM_PROMPT = SYSTEM_PROMPT.format(workspace = WORKSPACE)


# =============================================================================
# System Reminders - Soft prompts to encourage todo usage
# =============================================================================

# Shown at the start of conversation
INITIAL_REMINDER = "<reminder>Use TodoWrite for multi-step tasks.</reminder>"

# Shown if model hasn't updated todos in a while
NAG_REMINDER = "<reminder>10+ turns without todo update. Please update todos.</reminder>"

# =============================================================================
# Tool Definitions (v2 Tools + TodoWrite)
# =============================================================================
TOOLS = [
    # Tool 1: Bash - The gateway to execute everything 
    # Can run any command: git, pip, python, curl, etc.
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": """Execute shell command. Common patterns include:
- Read: cat/head/tail, grep/find/rg/ls, wc -l
- Write: echo 'content' > file, sed -i 's/old/new/g' file
- Subagent: python v1_bash_agent_demo/bash_agent.py 'task description' (spawns isolated agent, returns summary)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    }
                },
                "required": ["command"],
            }
        }
    },
    
    # Tool 2: Read File - For understanding existing code
    # Returns file content with optional line limit for large files
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file. Returns file content with optional line limit for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "The maximum number of lines to return (default is 1000).",
                    }
                },
                "required": ["file_path"],
            }
        }
    },

    # Tool 3: Write File - For modifying code or creating new files
    # Takes file path and content to write, creates file and parent directories automatically if not exist
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file.",
                    },
                },
                "required": ["file_path", "content"],
            }
        }
    },

    # Tool 4: Edit File - For modifying existing files with context
    # Uses unified diff format to specify edits, takes file path and diff content(old/next), applies changes to the file (creates backup before editing)
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace old content with new content in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit.",
                    },
                    "old_content":{
                        "type": "string",
                        "description": "The original content to be replaced.",
                    },
                    "new_content":{
                        "type": "string",
                        "description": "The new content to replace with.",
                    }
                }
            }
        }
    },

    # Tool 5: TodoWrite - For managing the structured todo list
    # Takes a complete new list of todos, validates it, and returns a rendered view
    {
        "type": "function",
        "function":{
            "name": "todo_write",
            "description": "Update tasks list. Use to plan and track multi-step tasks. Send the complete new list each time. Max 20 items, only one can be in_progress. Each item needs content, status (pending|in_progress|completed), and activeForm (present tense description of in_progress action). Returns rendered view of the todo list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "The complete new list of todo items.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "The description of the task.",
                                },
                                "status": {
                                    "type": "string",
                                    "description": "The status of the task (pending, in_progress, completed).",
                                },
                                "activeForm": {
                                    "type": "string",
                                    "description": "Present tense description of the in_progress action e.g. 'Reading files'.(required if status is in_progress).",
                                }
                            },
                            "required": ["content", "status", "activeForm"]
                        }
                    }
                },
                "required": ["items"],
            }
        }
    }
]

# =============================================================================
# Tool Implementations (v2 + TodoWrite)
# =============================================================================
def bash(command: str) -> dict:
    """
    Execute a shell command.

    Parameters:
        command: The shell command to execute.
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


def read_file(file_path: str, max_lines: int = 1000) -> dict:
    """
    Read content from a file.

    Parameters:
        file_path: The path to the file to read.
        max_lines: The maximum number of lines to return.
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
    Write content to a file.

    Parameters:
        file_path: The path to the file to write.
        content: The content to write to the file.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    path.parent.mkdir(parents = True, exist_ok = True)
    with path.open("w", encoding = "utf-8") as file:
        file.write(content)
    return {"status": "ok"}


def edit_file(file_path: str, old_content: str, new_content: str) -> dict:
    """
    Replace old content with new content in a file.

    Parameters:
        file_path: The path to the file to edit.
        old_content: The original content to be replaced.
        new_content: The new content to replace with.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    text = path.read_text(encoding = "utf-8", errors = "replace")
    if old_content not in text:
        return {"status": "not_found"}
    backup_path = path.with_suffix(path.suffix + ".bak")
    backup_path.write_text(text, encoding = "utf-8")
    updated = text.replace(old_content, new_content)
    path.write_text(updated, encoding = "utf-8")
    return {"status": "ok", "backup_path": str(backup_path)}


def todo_write(items: List[Dict]) -> dict:
    """
    Update the todo list and return the rendered view.

    Parameters:
        items: The complete new list of todo items.
    """
    try:
        rendered = Todo_Manager.update(items)
        return {"content": rendered}
    except ValueError as exc:
        return {"error": str(exc)}


def _parse_tool_args(arguments: str) -> Dict:
    """
    Parse tool call arguments safely.

    Parameters:
        arguments: JSON string arguments from tool call.
    """
    if not arguments:
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        try:
            return json.loads(arguments, strict = False)
        except json.JSONDecodeError:
            cleaned = "".join(
                ch for ch in arguments if ch >= " " or ch in "\t\n\r"
            )
            try:
                return json.loads(cleaned, strict = False)
            except json.JSONDecodeError as exc:
                logger.error(f"Failed to parse tool arguments: {exc}")
                return {}


def _assistant_turns_since_todo(history: List[Dict]) -> int:
    """
    Count assistant turns since the last todo_write tool call.

    Parameters:
        history: The chat history list of message dicts.
    """
    turns = 0
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls") or []
        for tool_call in tool_calls:
            if tool_call.get("function", {}).get("name") == "todo_write":
                return turns
        turns += 1
    return turns


def chat(
    prompt: Optional[str] = None,
    history: Optional[List] = None,
    runtime_options: Optional[RuntimeOptions] = None,
    trace_logger: Optional[TraceLogger] = None,
    session_store: Optional[SessionStore] = None,
    actor: str = "main",
    interactive: bool = True,
):
    """
    The agent loop to chat with LLM and execute tool calls.

    Parameters:
        prompt: The user prompt to start the chat.
        history: The chat history for multi-turn conversation.
        runtime_options: Runtime feature switches.
        trace_logger: Optional per-turn trace logger.
        session_store: Optional session persistence store.
        actor: Actor label for trace/session records.
        interactive: Whether to allow interactive reasoning expansion prompt.
    Returns:
        str: The final response from the agent.
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

    while True:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        if not history or len(history) == 1:
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
            return result.assistant_content

        results = []
        for tool_call in result.tool_calls:
            function_block = tool_call.get("function") or {}
            tool_name = function_block.get("name")
            args = _parse_tool_args(function_block.get("arguments"))

            if tool_name == "bash":
                cmd = args.get("command", "")
                print(f"\033[33m$ {cmd}\033[0m")
                output = bash(**args)
                combined = (output.get("stdout", "") or "") + (output.get("stderr", "") or "")
                print(combined or "(empty)")
            elif tool_name == "read_file":
                output = read_file(**args)
            elif tool_name == "write_file":
                output = write_file(**args)
            elif tool_name == "edit_file":
                output = edit_file(**args)
            elif tool_name == "todo_write":
                output = todo_write(**args)
                if output.get("content"):
                    print("\033[95mTodo List Updated:\033[0m")
                    print(output["content"])
            else:
                output = {"error": f"Unknown tool: {tool_name}"}

            session.record_tool(
                actor = actor,
                tool_name = tool_name or "unknown",
                arguments = args,
                output = output,
            )

            results.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": json.dumps(output, ensure_ascii = False)[:50000]
            })

        history.extend(results)


def parse_args():
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(description = "Todo Agent - Chat with LLM and use tools")
    parser.add_argument(
        "prompt",
        nargs = "?",
        help = "User prompt for the agent"
    )
    add_runtime_args(parser)

    args = parser.parse_args()
    args.runtime_options = runtime_options_from_args(args)
    return args


def main():
    """
    Main function to run the todo agent from command line.
    """
    args = parse_args()
    runtime_options = args.runtime_options

    logging.basicConfig(
        level = logging.INFO,
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers = [logging.StreamHandler()]
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
        logger.info("Starting Todo Agent in single-shot mode")
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
    else:
        logger.info("=" * 80)
        logger.info("Starting Todo Agent in interactive mode")
        logger.info("=" * 80)
        logger.info("Type 'exit' or 'quit' to end the conversation")
        logger.info("-" * 60)

        history = []
        try:
            while True:
                prompt = input("\033[94mUser:\033[0m ").strip()
                if prompt.lower() in ["exit", "quit"]:
                    logger.info("Conversation ended.")
                    break

                if not prompt:
                    continue

                result = chat(
                    prompt = prompt,
                    history = history,
                    runtime_options = runtime_options,
                    trace_logger = tracer,
                    session_store = session,
                    interactive = True,
                )
                if not runtime_options.stream:
                    print(f"\033[92mAssistant:\033[0m {result}")
        except KeyboardInterrupt:
            logger.info("\nConversation interrupted.")
        except Exception as exc:
            logger.error(f"Error: {exc}")
            return 1

    if session.get_path():
        logger.info(f"Session saved: {session.get_path()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
