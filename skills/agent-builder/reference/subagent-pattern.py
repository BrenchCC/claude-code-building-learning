"""
Subagent Pattern - Implement Task tool for context isolation.

Key idea:
Spawn child agents with isolated context so exploration noise does not
pollute the parent conversation history.
"""

import sys
import json
import time
from typing import Any, Dict, List


AGENT_TYPES: Dict[str, Dict[str, Any]] = {
    "explore": {
        "description": "Read-only agent for searching and analysis.",
        "tools": ["bash", "read_file"],
        "prompt": (
            "You are an exploration agent. Search and analyze code, "
            "but never modify files. Return a concise summary."
        ),
    },
    "code": {
        "description": "Implementation agent for coding and fixes.",
        "tools": "*",
        "prompt": (
            "You are a coding agent. Implement requested changes efficiently "
            "and return a summary of changes."
        ),
    },
    "plan": {
        "description": "Planning agent for strategy and sequencing.",
        "tools": ["bash", "read_file"],
        "prompt": (
            "You are a planning agent. Analyze and produce a numbered "
            "implementation plan. Do not modify files."
        ),
    },
}


def get_agent_descriptions(agent_types: Dict[str, Dict[str, Any]]) -> str:
    """
    Build textual agent type descriptions.

    Parameters:
        agent_types: Agent type registry with descriptions.
    """
    return "\n".join(
        f"- {name}: {config['description']}"
        for name, config in agent_types.items()
    )


def create_task_tool(agent_types: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create OpenAI function schema for Task tool.

    Parameters:
        agent_types: Agent type registry used for enum and docs.
    """
    return {
        "type": "function",
        "function": {
            "name": "Task",
            "description": (
                "Spawn a subagent in isolated context for focused subtasks.\n\n"
                "Agent types:\n"
                f"{get_agent_descriptions(agent_types = agent_types)}\n\n"
                "Examples:\n"
                "- Task(explore): find where auth is used\n"
                "- Task(plan): design migration steps\n"
                "- Task(code): implement registration flow"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Short task label for progress display.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Detailed instructions for the subagent.",
                    },
                    "agent_type": {
                        "type": "string",
                        "enum": list(agent_types.keys()),
                        "description": "Subagent type to spawn.",
                    },
                },
                "required": ["description", "prompt", "agent_type"],
            },
        },
    }


TASK_TOOL = create_task_tool(agent_types = AGENT_TYPES)


def _tool_name(tool: Dict[str, Any]) -> str:
    """
    Extract function tool name.

    Parameters:
        tool: Tool schema dictionary.
    """
    return tool.get("function", {}).get("name", "")


def get_tools_for_agent(
    agent_type: str,
    base_tools: List[Dict[str, Any]],
    agent_types: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Filter tools by agent type and remove recursive Task access.

    Parameters:
        agent_type: Selected subagent type key.
        base_tools: Parent tool list in OpenAI function format.
        agent_types: Agent registry defining permissions.
    """
    allowed = agent_types.get(agent_type, {}).get("tools", "*")

    filtered_tools = [
        tool for tool in base_tools
        if _tool_name(tool = tool) != "Task"
    ]

    if allowed == "*":
        return filtered_tools

    return [
        tool for tool in filtered_tools
        if _tool_name(tool = tool) in allowed
    ]


def _build_assistant_message(message: Any) -> Dict[str, Any]:
    """
    Convert OpenAI message object into history format.

    Parameters:
        message: OpenAI response message object.
    """
    assistant_message: Dict[str, Any] = {
        "role": "assistant",
        "content": message.content or "",
    }
    if message.tool_calls:
        assistant_message["tool_calls"] = []
        for tool_call in message.tool_calls:
            assistant_message["tool_calls"].append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
            )
    return assistant_message


def run_task(
    description: str,
    prompt: str,
    agent_type: str,
    client: Any,
    model: str,
    workdir: Any,
    base_tools: List[Dict[str, Any]],
    execute_tool: Any,
    agent_types: Dict[str, Dict[str, Any]] = AGENT_TYPES,
) -> str:
    """
    Execute subagent task in isolated context.

    Parameters:
        description: Short label shown in progress output.
        prompt: Detailed subtask instruction.
        agent_type: Agent type key in registry.
        client: OpenAI-compatible client object.
        model: Model name for subagent calls.
        workdir: Workspace path used in system prompt.
        base_tools: Parent tool list to derive allowed tools.
        execute_tool: Parent dispatcher for tool execution.
        agent_types: Agent type registry for permission lookup.
    """
    if agent_type not in agent_types:
        return f"Error: Unknown agent type '{agent_type}'"

    config = agent_types[agent_type]
    sub_system = (
        f"You are a {agent_type} subagent at {workdir}.\n\n"
        f"{config['prompt']}\n\n"
        "Complete the task and return a concise summary."
    )
    sub_tools = get_tools_for_agent(
        agent_type = agent_type,
        base_tools = base_tools,
        agent_types = agent_types,
    )
    sub_history: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    print(f"  [{agent_type}] {description}")
    start_time = time.time()
    tool_count = 0

    while True:
        messages = [{"role": "system", "content": sub_system}]
        messages.extend(sub_history)

        response = client.chat.completions.create(
            model = model,
            messages = messages,
            tools = sub_tools,
            max_tokens = 8000,
        )

        message = response.choices[0].message
        if message is None:
            return "Error: Subagent returned empty response."

        sub_history.append(_build_assistant_message(message = message))

        if not message.tool_calls:
            elapsed = time.time() - start_time
            sys.stdout.write(
                f"\r  [{agent_type}] {description} - done ({tool_count} tools, {elapsed:.1f}s)\n"
            )
            return message.content or "(subagent returned no text)"

        results: List[Dict[str, Any]] = []
        for tool_call in message.tool_calls:
            tool_count += 1
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            output = execute_tool(tool_name, tool_args)
            results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": output,
                }
            )

            elapsed = time.time() - start_time
            sys.stdout.write(
                f"\r  [{agent_type}] {description} ... {tool_count} tools, {elapsed:.1f}s"
            )
            sys.stdout.flush()

        sub_history.extend(results)


"""
Usage example in parent execute_tool dispatcher:

if name == "Task":
    return run_task(
        description = args["description"],
        prompt = args["prompt"],
        agent_type = args["agent_type"],
        client = client,
        model = MODEL,
        workdir = WORKDIR,
        base_tools = BASE_TOOLS,
        execute_tool = execute_tool,
    )
"""
