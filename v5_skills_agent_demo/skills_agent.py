#!/usr/bin/env python3
"""
v5_skills_agent.py - Mini Claude Code: Skills Mechanism (~550 lines)

Core Philosophy: "Knowledge Externalization"
============================================
v3 gave us subagents for task decomposition. But there's a deeper question:

    How does the model know HOW to handle domain-specific tasks?

- Processing PDFs? It needs to know pdftotext vs PyMuPDF
- Building MCP servers? It needs protocol specs and best practices
- Code review? It needs a systematic checklist

This knowledge isn't a tool - it's EXPERTISE. Skills solve this by letting
the model load domain knowledge on-demand.

The Paradigm Shift: Knowledge Externalization
--------------------------------------------
Traditional AI: Knowledge locked in model parameters
  - To teach new skills: collect data -> train -> deploy
  - Cost: $10K-$1M+, Timeline: Weeks
  - Requires ML expertise, GPU clusters

Skills: Knowledge stored in editable files
  - To teach new skills: write a SKILL.md file
  - Cost: Free, Timeline: Minutes
  - Anyone can do it

It's like attaching a hot-swappable LoRA adapter without any training!

Tools vs Skills:
---------------
    | Concept   | What it is              | Example                    |
    |-----------|-------------------------|---------------------------|
    | **Tool**  | What model CAN do       | bash, read_file, write    |
    | **Skill** | How model KNOWS to do   | PDF processing, MCP dev   |

Tools are capabilities. Skills are knowledge.

Progressive Disclosure:
----------------------
    Layer 1: Metadata (always loaded)      ~100 tokens/skill
             name + description only

    Layer 2: SKILL.md body (on trigger)    ~2000 tokens
             Detailed instructions

    Layer 3: Resources (as needed)         Unlimited
             scripts/, references/, assets/

This keeps context lean while allowing arbitrary depth.

SKILL.md Standard:
-----------------
    skills/
    |-- pdf/
    |   |-- SKILL.md          # Required: YAML frontmatter + Markdown body
    |-- mcp-builder/
    |   |-- SKILL.md
    |   |-- references/       # Optional: docs, specs
    |-- code-review/
        |-- SKILL.md
        |-- scripts/          # Optional: helper scripts

Cache-Preserving Injection:
--------------------------
Critical insight: Skill content goes into tool_result (user message),
NOT system prompt. This preserves prompt cache!

    Wrong: Edit system prompt each time (cache invalidated, 20-50x cost)
    Right: Append skill as tool result (prefix unchanged, cache hit)

This is how production Claude Code works - and why it's cost-efficient.

Usage:
    python v5_skills_agent_demo/skills_agent.py
"""

import os
import re
import sys
import json
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openai import OpenAI
from dotenv import load_dotenv

logger = logging.getLogger("V5-Subagent")

SYSTEM_PROMPT_PATH = "prompts/v5_subagent.md"

load_dotenv()

WORKSPACE = Path.cwd()
SKILLS_DIR = WORKSPACE / "skills"
MODEL = os.getenv("LLM_MODEL")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

# =============================================================================
# SkillLoader - The core addition in v4
# =============================================================================

class SkillLoader:
    """
    Loads and manages skills from SKILL.md files.

    A skill is a FOLDER containing:
    - SKILL.md (required): YAML frontmatter + markdown instructions
    - scripts/ (optional): Helper scripts the model can run
    - references/ (optional): Additional documentation
    - assets/ (optional): Templates, files for output

    SKILL.md Format:
    ----------------
        ---
        name: pdf
        description: Process PDF files. Use when reading, creating, or merging PDFs.
        ---

        # PDF Processing Skill

        ## Reading PDFs

        Use pdftotext for quick extraction:
        ```bash
        pdftotext input.pdf -
        ```
        ...

    The YAML frontmatter provides metadata (name, description).
    The markdown body provides detailed instructions.
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self.load_skills()

    def parse_skill_md(self, path: Path) -> dict:
        """
        Parse a SKILL.md file into metadata and body.

        Returns dict with: name, description, body, path, dir
        Returns None if file doesn't match format.
        """
        content = path.read_text()

        # Match YAML frontmatter between --- markers
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not match:
            return None

        frontmatter, body = match.groups()

        # Parse YAML-like frontmatter (simple key: value)
        metadata = {}
        for line in frontmatter.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")

        # Require name and description
        if "name" not in metadata or "description" not in metadata:
            return None

        return {
            "name": metadata["name"],
            "description": metadata["description"],
            "body": body.strip(),
            "path": path,
            "dir": path.parent,
        }

    def load_skills(self):
        """
        Scan skills directory and load all valid SKILL.md files.

        Only loads metadata at startup - body is loaded on-demand.
        This keeps the initial context lean.
        """
        if not self.skills_dir.exists():
            return

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill = self.parse_skill_md(skill_md)
            if skill:
                self.skills[skill["name"]] = skill

    def get_descriptions(self) -> str:
        """
        Generate skill descriptions for system prompt.

        This is Layer 1 - only name and description, ~100 tokens per skill.
        Full content (Layer 2) is loaded only when Skill tool is called.
        """
        if not self.skills:
            return "(no skills available)"

        return "\n".join(
            f"- {name}: {skill['description']}"
            for name, skill in self.skills.items()
        )

    def get_skill_content(self, name: str) -> str:
        """
        Get full skill content for injection.

        This is Layer 2 - the complete SKILL.md body, plus any available
        resources (Layer 3 hints).

        Returns None if skill not found.
        """
        if name not in self.skills:
            return None

        skill = self.skills[name]
        content = f"# Skill: {skill['name']}\n\n{skill['body']}"

        # List available resources (Layer 3 hints)
        resources = []
        for folder, label in [
            ("scripts", "Scripts"),
            ("references", "References"),
            ("assets", "Assets")
        ]:
            folder_path = skill["dir"] / folder
            if folder_path.exists():
                files = list(folder_path.glob("*"))
                if files:
                    resources.append(f"{label}: {', '.join(f.name for f in files)}")

        if resources:
            content += f"\n\n**Available resources in {skill['dir']}:**\n"
            content += "\n".join(f"- {r}" for r in resources)

        return content

    def list_skills(self) -> list:
        """Return list of available skill names."""
        return list(self.skills.keys())


# Global skill loader instance
SKILLS = SkillLoader(SKILLS_DIR)


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

# 
SKILLS_TOOL = {
    "type": "function",
    "function": {
        "name": "Skill",
        "description": f"""Load a skill to gain specialized knowledge for a task.

Available skills:
{SKILLS.get_descriptions()}

When to use:
- IMMEDIATELY when user task matches a skill description
- Before attempting domain-specific work (PDF, MCP, etc.)

The skill content will be injected into the conversation, giving you
detailed instructions and access to resources.""",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
                "args": {"type": "string"},
            },
            "required": ["skill_name"],
        },
    }
}
TOOLS = BASE_TOOLS + [TASK_TOOL, SKILLS_TOOL]

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

INITIAL_REMINDER = "<reminder>Use todo_write for multi-step tasks.</reminder>"
NAG_REMINDER = "<reminder>10+ turns without todo update. Please update todos via todo_write.</reminder>"
MAX_MAIN_ROUNDS = 40
MAX_SUBAGENT_ROUNDS = 30


def _load_system_prompt() -> str:
    """
    Load and hydrate the system prompt template.

    Returns:
        str: Fully formatted system prompt.
    """
    candidates = [
        Path(SYSTEM_PROMPT_PATH),
        WORKSPACE / SYSTEM_PROMPT_PATH,
        WORKSPACE / "prompts" / "v5_skills_agent.md",
    ]
    prompt_path = next((path for path in candidates if path.exists()), None)
    if not prompt_path:
        raise FileNotFoundError("System prompt file not found.")

    text = prompt_path.read_text(encoding = "utf-8")
    text = text.replace("{SKILLS.get_descriptions()}", SKILLS.get_descriptions())
    text = text.replace("{get_agent_descriptions()}", get_agent_descriptions())
    text = text.format(workspace = WORKSPACE)
    text += (
        "\n\nTool naming note:\n"
        "- The todo tool function name is `todo_write`.\n"
        "- Prefer Task only from the main agent."
    )
    return text


SYSTEM_PROMPT = _load_system_prompt()


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


def run_skill(skill_name: str, args: str = None) -> str:
    """
    Load a skill and return it as injectable tool_result content.

    Parameters:
        skill_name: Skill name declared in SKILL.md frontmatter.
        args: Optional skill arguments string for runtime hinting.
    """
    content = SKILLS.get_skill_content(skill_name)

    if content is None:
        available = ", ".join(SKILLS.list_skills()) or "none"
        return f"Error: Unknown skill '{skill_name}'. Available: {available}"

    args_text = (args or "").strip()
    safe_args_text = args_text.replace('"', "'")
    args_attr = f' args="{safe_args_text}"' if safe_args_text else ""
    return f"""<skill-loaded name="{skill_name}"{args_attr}>
{content}
</skill-loaded>

Follow the instructions in the skill above to complete the user's task."""


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


def _execute_tool_call(
    tool_name: str,
    args: Dict,
    skills_used: Optional[List[str]] = None
) -> Dict:
    """
    Execute a tool by name and return a JSON-serializable dict.

    Parameters:
        tool_name: Tool function name.
        args: Parsed tool argument dict.
        skills_used: Mutable list to record successfully loaded skill names.
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
            skills_used = skills_used
        )
        return {"content": summary}
    if tool_name == "Skill":
        skill_name = args.get("skill_name", "").strip()
        skill_args = args.get("args")
        if not skill_name:
            return {"error": "Skill requires non-empty skill_name."}
        content = run_skill(skill_name = skill_name, args = skill_args)
        if content.startswith("Error:"):
            return {"error": content}
        if skills_used is not None and skill_name not in skills_used:
            skills_used.append(skill_name)
        return {"content": content, "skill_name": skill_name}

    return {"error": f"Unknown tool: {tool_name}"}


def _safe_call_tool(
    tool_name: str,
    args: Dict,
    skills_used: Optional[List[str]] = None
) -> Tuple[Dict, Optional[str]]:
    """
    Execute a tool call with exception protection.

    Parameters:
        tool_name: Tool function name.
        args: Parsed tool argument dict.
        skills_used: Mutable list to record successfully loaded skill names.
    """
    try:
        return (
            _execute_tool_call(
                tool_name = tool_name,
                args = args,
                skills_used = skills_used
            ),
            None
        )
    except TypeError as exc:
        return {}, f"Tool '{tool_name}' argument error: {exc}"
    except Exception as exc:
        return {}, f"Tool '{tool_name}' runtime error: {exc}"


def _format_tool_result(tool_call_id: str, tool_name: str, output: Dict) -> Dict:
    """
    Format a tool result message, injecting skill content when needed.

    Parameters:
        tool_call_id: Tool call identifier from the model.
        tool_name: Tool function name.
        output: Tool output payload.
    """
    if tool_name == "Skill" and output.get("content"):
        content = output["content"]
    else:
        content = json.dumps(output, ensure_ascii = False)[:50000]
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


def _render_skill_usage_note(skills_used: List[str]) -> str:
    """
    Render skill usage note for final response visibility.

    Parameters:
        skills_used: Ordered skill names loaded in current request.
    """
    used = ", ".join(skills_used) if skills_used else "none"
    return f"<skill-usage>\nused_skills: {used}\n</skill-usage>"


def run_task(
    description: str,
    prompt: str,
    agent_type: str,
    skills_used: Optional[List[str]] = None
) -> str:
    """
    Spawn and run a subagent in isolated context.

    Parameters:
        description: Human-readable subtask description.
        prompt: Prompt sent to the subagent.
        agent_type: Subagent type key (explore|code|plan).
        skills_used: Mutable list to record successfully loaded skill names.
    """
    config = AGENT_TYPE_REGISTRY.get(agent_type)
    if not config:
        return f"Error: Unknown agent type '{agent_type}'"

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
        response = LLM_SERVER.chat.completions.create(
            model = MODEL,
            messages = [{"role": "system", "content": sub_system_prompt}] + sub_messages,
            tools = sub_tools,
            max_tokens = 8192,
        )
        llm_response = response.choices[0].message

        assistant_message = {
            "role": "assistant",
            "content": llm_response.content or "",
        }
        if llm_response.tool_calls:
            assistant_message["tool_calls"] = []
            for tool_call in llm_response.tool_calls:
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

        sub_messages.append(assistant_message)

        if not llm_response.tool_calls:
            elapsed = time.time() - start_time
            print(f"  [{agent_type}] {description} - done ({tool_count} tools, {elapsed:.1f}s)")
            return llm_response.content or "(subagent returned no text)"

        tool_results = []
        for tool_call in llm_response.tool_calls:
            tool_name = tool_call.function.name
            args = _parse_tool_args(tool_call.function.arguments)
            output, error = _safe_call_tool(
                tool_name = tool_name,
                args = args,
                skills_used = skills_used
            )
            if error:
                output = {"error": error}

            tool_count += 1
            elapsed = time.time() - start_time
            sys.stdout.write(
                f"\r  [{agent_type}] {description} ... {tool_count} tools, {elapsed:.1f}s"
            )
            sys.stdout.flush()

            tool_results.append(
                _format_tool_result(
                    tool_call_id = tool_call.id,
                    tool_name = tool_name,
                    output = output,
                )
            )

        sub_messages.extend(tool_results)

    return (
        f"Subagent stopped after reaching max rounds ({MAX_SUBAGENT_ROUNDS}). "
        f"Last task: {description}"
    )


def chat(prompt: Optional[str] = None, history: Optional[List[Dict]] = None) -> str:
    """
    Main agent loop with tool-calling and subagent orchestration.

    Parameters:
        prompt: User input string.
        history: Existing message history for multi-turn mode.
    """
    if history is None:
        history = []
    if prompt:
        history.append({"role": "user", "content": prompt})
    skills_used = []

    for _ in range(MAX_MAIN_ROUNDS):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if len(history) <= 1:
            messages.append({"role": "system", "content": INITIAL_REMINDER})
        elif _assistant_turns_since_todo(history) >= 10:
            messages.append({"role": "system", "content": NAG_REMINDER})

        messages.extend(history)

        response = LLM_SERVER.chat.completions.create(
            model = MODEL,
            messages = messages,
            tools = TOOLS,
            max_tokens = 8192,
        )
        llm_response = response.choices[0].message

        assistant_message = {
            "role": "assistant",
            "content": llm_response.content or "",
        }
        if llm_response.tool_calls:
            assistant_message["tool_calls"] = []
            for tool_call in llm_response.tool_calls:
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

        history.append(assistant_message)

        if not llm_response.tool_calls:
            result = llm_response.content or ""
            return f"{result}\n\n{_render_skill_usage_note(skills_used)}"

        tool_results = []
        for tool_call in llm_response.tool_calls:
            tool_name = tool_call.function.name
            args = _parse_tool_args(tool_call.function.arguments)
            output, error = _safe_call_tool(
                tool_name = tool_name,
                args = args,
                skills_used = skills_used
            )
            if error:
                output = {"error": error}
            tool_results.append(
                _format_tool_result(
                    tool_call_id = tool_call.id,
                    tool_name = tool_name,
                    output = output,
                )
            )

        history.extend(tool_results)

    result = (
        f"Stopped after reaching max rounds ({MAX_MAIN_ROUNDS}). "
        "The conversation may be stuck in repeated tool calls."
    )
    return f"{result}\n\n{_render_skill_usage_note(skills_used)}"


def parse_args():
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description = "Skills Agent - Chat with LLM and use tools"
    )
    parser.add_argument(
        "prompt",
        nargs = "?",
        help = "User prompt for the agent"
    )

    return parser.parse_args()


def main():
    """
    Main function to run the skills agent from command line.
    """
    args = parse_args()

    logging.basicConfig(
        level = logging.INFO,
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers = [logging.StreamHandler()]
    )

    if args.prompt:
        logger.info("=" * 80)
        logger.info("Starting Skills Agent in single-shot mode")
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
        logger.info("=" * 80)
        logger.info("Starting Skills Agent in interactive mode")
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


if __name__ == "__main__":
    sys.exit(main())
