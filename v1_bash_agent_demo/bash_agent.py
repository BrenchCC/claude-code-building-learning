import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.llm_call import build_assistant_message, call_chat_completion
from utils.reasoning_renderer import ReasoningRenderer
from utils.runtime_config import RuntimeOptions, add_runtime_args, runtime_options_from_args
from utils.session_store import SessionStore
from utils.thinking_policy import build_thinking_params, resolve_thinking_policy
from utils.trace_logger import TraceLogger


logger = logging.getLogger("V1-Bash-Agent")

load_dotenv()

SYSTEM_PROMPT_PATH = "prompts/v1_bash_agent.md"

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)
MODEL = os.getenv("LLM_MODEL")

TOOL = [
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
            },
        },
    }
]

with open(SYSTEM_PROMPT_PATH, "r", encoding = "utf-8") as file:
    SYSTEM_PROMPT = file.read()
SYSTEM_PROMPT = SYSTEM_PROMPT.format(path = os.getcwd())


def chat(
    prompt: Optional[str] = None,
    history: Optional[List[Dict]] = None,
    runtime_options: Optional[RuntimeOptions] = None,
    trace_logger: Optional[TraceLogger] = None,
    session_store: Optional[SessionStore] = None,
    actor: str = "main",
    interactive: bool = True,
):
    """
    The agent to chat with LLM and execute bash commands, all loop inside this function.

    Args:
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
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
            tools = TOOL,
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

            if tool_name != "bash":
                output = {"error": f"Unknown tool: {tool_name}"}
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": json.dumps(output, ensure_ascii = False)[:50000],
                    }
                )
                continue

            args = _parse_tool_args(function_block.get("arguments", "{}"))
            command = args.get("command", "")
            print(f"\033[33m$ {command}\033[0m")

            try:
                out = subprocess.run(
                    command,
                    shell = True,
                    capture_output = True,
                    text = True,
                    timeout = 300,
                    cwd = os.getcwd(),
                )
                output_text = (out.stdout or "") + (out.stderr or "")
            except subprocess.TimeoutExpired:
                output_text = "(timeout after 300s)"

            print(output_text or "(empty)")
            output_payload = {
                "stdout_stderr": output_text,
            }
            session.record_tool(
                actor = actor,
                tool_name = "bash",
                arguments = args,
                output = output_payload,
            )

            results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": output_text[:50000],
                }
            )

        history.extend(results)


def _parse_tool_args(arguments: str) -> Dict:
    """Parse tool call arguments safely."""
    if not arguments:
        return {}

    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        cleaned = "".join(character for character in arguments if character >= " " or character in "\t\n\r")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


def parse_args():
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(description = "Bash Agent - Chat with LLM and execute shell commands")
    parser.add_argument(
        "prompt",
        nargs = "?",
        help = "User prompt for the agent",
    )
    add_runtime_args(parser)

    args = parser.parse_args()
    args.runtime_options = runtime_options_from_args(args)
    return args


def main():
    """
    Main function to run the bash agent from command line.
    """
    args = parse_args()
    runtime_options = args.runtime_options

    logging.basicConfig(
        level = logging.INFO,
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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
        logger.info("Starting Bash Agent in single-shot mode")
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
        logger.info("Starting Bash Agent in interactive mode")
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
