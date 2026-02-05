import os
import sys
import json
import logging
import subprocess
from typing import List

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger("V1-Bash-Agent")

load_dotenv()

SYSTEM_PROMPT_PATH = "prompts/v1_bash_agent.md"

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)
MODEL = os.getenv("LLM_MODEL")

# TODO: finish the bash agent

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
            }
        }
    }
]

with open(SYSTEM_PROMPT_PATH, "r") as f:
    SYSTEM_PROMPT = f.read()
SYSTEM_PROMPT = SYSTEM_PROMPT.format(path = os.getcwd())

def chat(prompt: str = None, history: List = None):
    """
    The agent to chat with LLM and execute bash commands, all loop inside this function.
    The main pattern for each loop is:
        while True:
            response = LLM(messages, tools)
            if response is tool_call:
                execute tool
                add observation to messages
            else:
                return response
    Args:
        prompt (str): The user prompt to start the chat.
        history (list, optional): The chat history for multi-turn conversation. Defaults to None.
    Returns:
        str: The final response from the agent.
    """
    if not history:
        history = []

    history.append({"role": "user", "content": prompt})

    while True:
        # 1. Call LLM with messages and tools
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        messages.extend(history)

        response = LLM_SERVER.chat.completions.create(
            model = MODEL,
            messages = messages,
            tools = TOOL,
            max_tokens = 8192
        )

        # 2. Parse LLM response, build assistant message
        llm_response = response.choices[0].message

        if llm_response is None:
            raise ValueError("LLM response is None")

        # Build assistant message in OpenAI-compatible format
        assistant_message = {
            "role": "assistant",
            "content": llm_response.content or ""
        }

        if llm_response.tool_calls:
            assistant_message["tool_calls"] = []
            for tool_call in llm_response.tool_calls:
                assistant_message["tool_calls"].append({
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })

        history.append(assistant_message)

        # 3. If model didn't call tools, we're done
        if not llm_response.tool_calls:
            return llm_response.content

        # 4. Execute each tool call and collect results
        results = []
        for tool_call in llm_response.tool_calls:
            if tool_call.function.name == "bash":
                args = json.loads(tool_call.function.arguments)
                cmd = args["command"]
                print(f"\033[33m$ {cmd}\033[0m")  # Yellow color for commands

                try:
                    out = subprocess.run(
                        cmd,
                        shell = True,
                        capture_output = True,
                        text = True,
                        timeout = 300,
                        cwd = os.getcwd()
                    )
                    output = out.stdout + out.stderr
                except subprocess.TimeoutExpired:
                    output = "(timeout after 300s)"

                print(output or "(empty)")
                results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": output[:50000]  # Truncate very long outputs
                })

        # 5. Append results and continue the loop
        history.extend(results)


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
        help = "User prompt for the agent"
    )

    return parser.parse_args()


def main():
    """
    Main function to run the bash agent from command line.
    """
    args = parse_args()

    # Configure logging
    logging.basicConfig(
        level = logging.INFO,
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers = [logging.StreamHandler()]
    )

    if args.prompt:
        # Run in single-shot mode
        logger.info("=" * 80)
        logger.info("Starting Bash Agent in single-shot mode")
        logger.info("=" * 80)

        try:
            result = chat(args.prompt)
            logger.info("-" * 60)
            logger.info("Final Response:")
            logger.info("-" * 60)
            print(result)
        except Exception as e:
            logger.error(f"Error: {e}")
            return 1
    else:
        # Run in interactive mode
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

                result = chat(prompt, history)
                print(f"\033[92mAssistant:\033[0m {result}")
        except KeyboardInterrupt:
            logger.info("\nConversation interrupted.")
        except Exception as e:
            logger.error(f"Error: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
        
