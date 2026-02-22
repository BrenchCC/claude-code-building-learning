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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.llm_call import build_assistant_message, call_chat_completion
from utils.reasoning_renderer import ReasoningRenderer
from utils.runtime_config import RuntimeOptions, add_runtime_args, runtime_options_from_args
from utils.session_store import SessionStore
from utils.thinking_policy import ThinkingPolicyState, build_thinking_params, resolve_thinking_policy
from utils.trace_logger import TraceLogger

logger = logging.getLogger("V6-Compression-Agent")

SYSTEM_PROMPT_PATH = "prompts/v6_compression_agent.md"

load_dotenv()

WORKSPACE = Path.cwd()
SKILLS_DIR = WORKSPACE / "skills"
TRANSCRIPTS_DIR = WORKSPACE / "transcripts"
MODEL = os.getenv("LLM_MODEL")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

# Micro-compact savings threshold: only clear old tool results if estimated
# savings >= this value.
MIN_SAVINGS = 20000
MAX_RESTORE_FILES = 5
MAX_RESTORE_TOKENS_PER_FILE = 5000
MAX_RESTORE_TOKENS_TOTAL = 50000
IMAGE_TOKEN_ESTIMATE = 2000

# Context window management
def auto_compact_threshold(context_window: int = 200000, max_output: int = 16384) -> int:
    """Dynamic threshold: context_window - min(max_output, 20000) - 13000.
    For a 200K window with 16K output: 200000 - 16384 - 13000 = 170616."""
    output_reserve = min(max_output, 20000)
    return context_window - output_reserve - 13000

class ContextManager:
    """
    Three-layer context compression to keep conversations within window limits.

    Human working memory is limited too - we don't remember every line of code
    we wrote, just "what we did, why, and current state". Compression mimics
    this cognitive pattern:
    - Micro-compact = short-term memory auto-decay
    - Auto-compact  = detail memory -> concept memory
    - Disk transcript = long-term memory archive
    """

    COMPACTABLE_TOOLS = {"bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "notebook_edit"}
    KEEP_RECENT = 3
    TOKEN_THRESHOLD = auto_compact_threshold()
    MAX_OUTPUT_TOKENS = 40000

    def __init__(self, max_context_tokens: int = 200000):
        self.max_context_tokens = max_context_tokens
        TRANSCRIPTS_DIR.mkdir(exist_ok = True)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return len(text) // 4
    
    def micro_compact(self, messages: List[Dict]) -> List[Dict]:
        """
        Micro-compaction: remove old tool results that are unlikely to be relevant.
        The first layer: replaces old tool calls with a placeholder.
    
        Keeps the tool call structure intact - the model still knows WHAT
        it called, just can't see the old output. It can re-read if needed.
        Only applies clearing if total estimated savings >= MIN_SAVINGS.
        """
        tool_results = []
        tool_call_map = self._build_tool_call_map(messages)

        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                tool_name = msg.get("name") or tool_call_map.get(tool_call_id, "")
                if tool_name in self.COMPACTABLE_TOOLS:
                    tool_results.append(("openai", msg))
                continue

            if role != "user":
                continue

            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_name = self._find_tool_name(messages, block.get("tool_use_id", ""))
                    if tool_name in self.COMPACTABLE_TOOLS:
                        tool_results.append(("anthropic", block))

        # Keep only the most recent KEEP_RECENT, compact the rest
        to_compact = tool_results[:-self.KEEP_RECENT] if len(tool_results) > self.KEEP_RECENT else []

        # Estimate total savings before clearing; skip if below threshold
        estimated_savings = 0
        clearable = []
        for kind, payload in to_compact:
            content_str = payload.get("content", "")
            if not isinstance(content_str, str):
                content_str = json.dumps(content_str, default = str)
            if self.estimate_tokens(content_str) > 1000:
                estimated_savings += self.estimate_tokens(content_str)
                clearable.append(payload)

        if estimated_savings >= MIN_SAVINGS:
            for payload in clearable:
                payload["content"] = "[Old tool result content cleared]"

        return messages
    
    def should_compact(self, messages: list) -> bool:
        """Check if context is approaching the window limit."""
        total = sum(self.estimate_tokens(json.dumps(m, default = str)) for m in messages)
        return total > self.TOKEN_THRESHOLD
    def auto_compact(self, messages: list) -> list:
        """
        Layer 2: Summarize entire conversation, replace ALL messages.

        Replaces the ENTIRE message list with:
        [user_summary_message, assistant_ack, ...restored_file_messages].
        There is no "keep last N messages" behavior in auto_compact.
        Only manual /compact can optionally preserve messages.

        1. Save full transcript to disk (never lose data)
        2. Call model to generate chronological summary
        3. Replace all messages with summary + restored files
        """
        self.save_transcript(messages)

        # Capture file access history before compaction
        restored_files = self.restore_recent_files(messages)

        conversation_text = self._messages_to_text(messages)

        summary_result = call_chat_completion(
            client = LLM_SERVER,
            model = MODEL,
            messages = [
                {
                    "role": "system",
                    "content": "You are a conversation summarizer. Be concise but thorough.",
                },
                {
                    "role": "user",
                    "content": (
                        "Summarize this conversation chronologically. Include: goals, actions taken, "
                        "decisions made, current state, and pending work.\n\n"
                        f"{conversation_text[:100000]}"
                    ),
                },
            ],
            max_tokens = 2000,
        )

        summary = summary_result.assistant_content.strip()

        # Replace ALL messages with summary + restored files (no "keep last N")
        result = [
            {"role": "user", "content": f"[Conversation compressed]\n\n{summary}"},
            {"role": "assistant", "content": "Understood. I have the context from the compressed conversation. Continuing work."},
        ]
        # Interleave restored files as user/assistant pairs to maintain valid turn order
        for rf in restored_files:
            result.append(rf)
            result.append({"role": "assistant", "content": "Noted, file content restored."})
        return result

    def handle_large_output(self, output: str) -> str:
        """
        Handle oversized tool output: save to disk, return preview.
        """
        if self.estimate_tokens(output) <= self.MAX_OUTPUT_TOKENS:
            return output

        filename = f"output_{int(time.time())}.txt"
        path = TRANSCRIPTS_DIR / filename
        path.write_text(output)

        preview = output[:2000]
        return f"Output too large ({self.estimate_tokens(output)} tokens). Saved to: {path}\n\nPreview:\n{preview}..."

    def save_transcript(self, messages: list):
        """Append full transcript to disk. The permanent archive."""
        path = TRANSCRIPTS_DIR / "transcript.jsonl"
        with open(path, "a") as f:
            for msg in messages:
                f.write(json.dumps(msg, default = str) + "\n")

    def restore_recent_files(self, messages: list) -> list:
        """After auto-compact, re-inject recently-read files into context.
        Scans conversation history for read_file calls and returns restoration
        messages for the most recently accessed files within token limits."""
        file_cache = {}
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("name") == "read_file":
                    path = block.get("input", {}).get("path", "")
                    if path:
                        file_cache[path] = len(file_cache)
                elif hasattr(block, "name") and block.name == "read_file":
                    path = getattr(block, "input", {}).get("path", "")
                    if path:
                        file_cache[path] = len(file_cache)

        restored = []
        total_tokens = 0
        # Sort by access order (most recent last -> reverse for most recent first)
        sorted_paths = sorted(file_cache.keys(), key=lambda p: file_cache[p], reverse=True)
        for path in sorted_paths[:MAX_RESTORE_FILES]:
            try:
                full_path = (WORKSPACE / path).resolve()
                if not full_path.is_relative_to(WORKSPACE) or not full_path.exists():
                    continue
                content = full_path.read_text()
                tokens = self.estimate_tokens(content)
                if tokens > MAX_RESTORE_TOKENS_PER_FILE:
                    continue
                if total_tokens + tokens > MAX_RESTORE_TOKENS_TOTAL:
                    break
                restored.append({
                    "role": "user",
                    "content": f"[Restored after compact] {path}:\n{content}"
                })
                total_tokens += tokens
            except (OSError, ValueError):
                continue
        return restored

    def _find_tool_name(self, messages: list, tool_use_id: str) -> str:
        """Find tool name from a tool_use_id in message history."""
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if isinstance(tool_call, dict) and tool_call.get("id") == tool_use_id:
                        function_payload = tool_call.get("function", {})
                        return function_payload.get("name", "")
                    if hasattr(tool_call, "id") and tool_call.id == tool_use_id:
                        function_payload = getattr(tool_call, "function", None)
                        if function_payload:
                            return getattr(function_payload, "name", "")
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "id") and block.id == tool_use_id:
                        return block.name
                    if isinstance(block, dict) and block.get("id") == tool_use_id:
                        return block.get("name", "")
        return ""

    def _build_tool_call_map(self, messages: list) -> Dict[str, str]:
        """Build a map of tool_call_id -> tool name for OpenAI-style tool calls."""
        tool_call_map = {}
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            tool_calls = msg.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                tool_id = None
                tool_name = None
                if isinstance(tool_call, dict):
                    tool_id = tool_call.get("id")
                    function_payload = tool_call.get("function", {})
                    tool_name = function_payload.get("name")
                else:
                    tool_id = getattr(tool_call, "id", None)
                    function_payload = getattr(tool_call, "function", None)
                    if function_payload is not None:
                        tool_name = getattr(function_payload, "name", None)
                if tool_id and tool_name:
                    tool_call_map[tool_id] = tool_name
        return tool_call_map

    def _messages_to_text(self, messages: list) -> str:
        """Convert messages to plain text for summarization."""
        lines = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                tool_name = msg.get("name", "")
                if tool_name:
                    lines.append(f"[tool:{tool_name}] {str(content)[:500]}")
                else:
                    lines.append(f"[tool:{tool_call_id}] {str(content)[:500]}")
                continue
            if isinstance(content, str):
                lines.append(f"[{role}] {content[:500]}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_result":
                            text = str(block.get("content", ""))[:200]
                            lines.append(f"[tool_result] {text}")
                        elif block.get("type") == "text":
                            lines.append(f"[{role}] {block.get('text', '')[:500]}")
                    elif hasattr(block, "text"):
                        lines.append(f"[{role}] {block.text[:500]}")
        return "\n".join(lines)


# Global context manager
CTX = ContextManager()

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
        WORKSPACE / "prompts" / "v6_compression_agent.md",
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


def _render_skill_usage_note(skills_used: List[str]) -> str:
    """
    Render skill usage note for final response visibility.

    Parameters:
        skills_used: Ordered skill names loaded in current request.
    """
    used = ", ".join(skills_used) if skills_used else "none"
    return f"<skill-usage>\nused_skills: {used}\n</skill-usage>"


def _format_tool_result(
    tool_call_id: str,
    tool_name: str,
    output: Dict,
    context_manager: ContextManager,
) -> Dict:
    """
    Format a tool result message, injecting skill content when needed.

    Parameters:
        tool_call_id: Tool call identifier from the model.
        tool_name: Tool function name.
        output: Tool output payload.
        context_manager: Context manager for large output handling.
    """
    if tool_name == "Skill" and output.get("content"):
        content = output["content"]
    else:
        raw_content = json.dumps(output, ensure_ascii = False)[:50000]
        content = context_manager.handle_large_output(raw_content)
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


class Agent:
    """
    Agent with state, tool calling, subagent spawning, and compression.
    """

    def __init__(
        self,
        runtime_options: Optional[RuntimeOptions] = None,
        trace_logger: Optional[TraceLogger] = None,
        session_store: Optional[SessionStore] = None,
        thinking_policy: Optional[ThinkingPolicyState] = None,
        context_manager: Optional[ContextManager] = None,
        actor: str = "main",
        system_prompt: str = SYSTEM_PROMPT,
        tools: Optional[List[Dict]] = None,
    ):
        """
        Initialize agent state and runtime components.

        Parameters:
            runtime_options: Runtime feature switches.
            trace_logger: Optional per-turn trace logger.
            session_store: Optional session persistence store.
            thinking_policy: Resolved thinking policy shared with parent loop.
            context_manager: Context compression manager.
            actor: Actor label for trace/session records.
            system_prompt: System prompt for the agent.
            tools: Tool schema list for the agent.
        """
        self.options = runtime_options or RuntimeOptions()
        self.tracer = trace_logger or TraceLogger(
            enabled = self.options.show_llm_response
        )
        self.session = session_store or SessionStore(
            enabled = self.options.save_session,
            model = MODEL,
            session_dir = self.options.session_dir,
            runtime_options = self.options.as_dict(),
        )
        self.thinking_policy = thinking_policy or resolve_thinking_policy(
            client = LLM_SERVER,
            model = MODEL,
            capability_setting = self.options.thinking_capability,
            param_style_setting = self.options.thinking_param_style,
        )
        self.renderer = ReasoningRenderer(
            preview_chars = self.options.reasoning_preview_chars
        )
        self.context_manager = context_manager or CTX
        self.actor = actor
        self.system_prompt = system_prompt
        self.tools = tools or TOOLS
        self.history: List[Dict] = []
        self.skills_used: List[str] = []

    def run(
        self,
        prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        interactive: bool = True,
    ) -> str:
        """
        Main agent loop with tool-calling and subagent orchestration.

        Parameters:
            prompt: User input string.
            history: Existing message history for multi-turn mode.
            interactive: Whether to allow interactive reasoning expansion prompt.
        """
        if history is not None:
            self.history = history
        if prompt:
            self.history.append({"role": "user", "content": prompt})

        for _ in range(MAX_MAIN_ROUNDS):
            if self.context_manager.should_compact(self.history):
                self.history = self.context_manager.auto_compact(self.history)
            self.history = self.context_manager.micro_compact(self.history)

            messages = [{"role": "system", "content": self.system_prompt}]

            if len(self.history) <= 1:
                messages.append({"role": "system", "content": INITIAL_REMINDER})
            elif _assistant_turns_since_todo(self.history) >= 10:
                messages.append({"role": "system", "content": NAG_REMINDER})

            messages.extend(self.history)

            result = self._call_llm(
                messages = messages,
                tools = self.tools,
                max_tokens = 8192,
                interactive = interactive,
                allow_expand_prompt = True,
            )

            assistant_message = build_assistant_message(result)
            self.history.append(assistant_message)

            rendered_reasoning = (
                result.assistant_reasoning if self._show_reasoning() else ""
            )
            self._log_turn(result, rendered_reasoning)

            if not result.tool_calls:
                final_text = result.assistant_content or ""
                return f"{final_text}\n\n{_render_skill_usage_note(self.skills_used)}"

            tool_results = self._handle_tool_calls(
                tool_calls = result.tool_calls,
                interactive = interactive,
            )
            self.history.extend(tool_results)

        result = (
            f"Stopped after reaching max rounds ({MAX_MAIN_ROUNDS}). "
            "The conversation may be stuck in repeated tool calls."
        )
        return f"{result}\n\n{_render_skill_usage_note(self.skills_used)}"

    def run_subagent(
        self,
        description: str,
        prompt: str,
        agent_type: str,
    ) -> str:
        """
        Spawn and run a subagent in isolated context.

        Parameters:
            description: Human-readable subtask description.
            prompt: Prompt sent to the subagent.
            agent_type: Subagent type key (explore|code|plan).
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
        sub_actor = f"subagent:{agent_type}"
        start_time = time.time()
        tool_count = 0

        print(f"  [{agent_type}] {description}")

        for _ in range(MAX_SUBAGENT_ROUNDS):
            if self.context_manager.should_compact(sub_messages):
                sub_messages = self.context_manager.auto_compact(sub_messages)
            sub_messages = self.context_manager.micro_compact(sub_messages)

            result = self._call_llm(
                messages = [{"role": "system", "content": sub_system_prompt}] + sub_messages,
                tools = sub_tools,
                max_tokens = 8192,
                interactive = False,
                allow_expand_prompt = False,
            )

            assistant_message = build_assistant_message(result)
            sub_messages.append(assistant_message)

            rendered_reasoning = (
                result.assistant_reasoning if self._show_reasoning() else ""
            )
            self._log_turn(result, rendered_reasoning, actor = sub_actor)

            if not result.tool_calls:
                elapsed = time.time() - start_time
                print(
                    f"  [{agent_type}] {description} - done "
                    f"({tool_count} tools, {elapsed:.1f}s)"
                )
                return result.assistant_content or "(subagent returned no text)"

            tool_results = []
            for tool_call in result.tool_calls:
                function_block = tool_call.get("function") or {}
                tool_name = function_block.get("name")
                args = _parse_tool_args(function_block.get("arguments"))
                output, error = self._safe_call_tool(
                    tool_name = tool_name,
                    args = args,
                    interactive = False,
                )
                if error:
                    output = {"error": error}

                tool_count += 1
                elapsed = time.time() - start_time
                sys.stdout.write(
                    f"\r  [{agent_type}] {description} ... "
                    f"{tool_count} tools, {elapsed:.1f}s"
                )
                sys.stdout.flush()

                self.session.record_tool(
                    actor = sub_actor,
                    tool_name = tool_name or "unknown",
                    arguments = args,
                    output = output,
                )

                tool_results.append(
                    _format_tool_result(
                        tool_call_id = tool_call.get("id"),
                        tool_name = tool_name,
                        output = output,
                        context_manager = self.context_manager,
                    )
                )

            sub_messages.extend(tool_results)

        return (
            f"Subagent stopped after reaching max rounds ({MAX_SUBAGENT_ROUNDS}). "
            f"Last task: {description}"
        )

    def _call_llm(
        self,
        messages: List[Dict],
        tools: List[Dict],
        max_tokens: int,
        interactive: bool,
        allow_expand_prompt: bool,
    ):
        """
        Call the LLM with streaming and reasoning rendering support.

        Parameters:
            messages: Messages payload for the model.
            tools: Tool schema list for the model call.
            max_tokens: Max tokens for response.
            interactive: Whether to allow interactive reasoning expansion.
            allow_expand_prompt: Whether to allow expand prompt on finalize.
        """
        self.renderer.reset_turn()
        show_reasoning = self._show_reasoning()

        def _on_content_chunk(chunk: str) -> None:
            if not self.options.stream or not chunk:
                return
            sys.stdout.write(chunk)
            sys.stdout.flush()

        def _on_reasoning_chunk(chunk: str) -> None:
            if not self.options.stream or not show_reasoning:
                return
            self.renderer.handle_stream_chunk(chunk)

        result = call_chat_completion(
            client = LLM_SERVER,
            model = MODEL,
            messages = messages,
            tools = tools,
            max_tokens = max_tokens,
            stream = self.options.stream,
            thinking_params = build_thinking_params(
                policy = self.thinking_policy,
                thinking_mode = self.options.thinking_mode,
                reasoning_effort = self.options.reasoning_effort,
            ),
            on_content_chunk = _on_content_chunk,
            on_reasoning_chunk = _on_reasoning_chunk,
        )

        if self.options.stream and result.assistant_content:
            sys.stdout.write("\n")
            sys.stdout.flush()

        rendered_reasoning = result.assistant_reasoning if show_reasoning else ""
        self.renderer.finalize_turn(
            full_reasoning = rendered_reasoning,
            stream_mode = self.options.stream,
            allow_expand_prompt = allow_expand_prompt and not result.tool_calls,
            interactive = interactive,
        )

        return result

    def _show_reasoning(self) -> bool:
        """
        Determine whether reasoning should be shown.
        """
        return self.options.thinking_mode != "off"

    def _log_turn(self, result, rendered_reasoning: str, actor: Optional[str] = None) -> None:
        """
        Log assistant turn to trace and session stores.

        Parameters:
            result: LLM call result object.
            rendered_reasoning: Rendered reasoning text.
            actor: Actor label override.
        """
        actor_name = actor or self.actor
        self.tracer.log_turn(
            actor = actor_name,
            assistant_content = result.assistant_content,
            tool_calls = result.tool_calls,
            assistant_reasoning = rendered_reasoning,
        )
        self.session.record_assistant(
            actor = actor_name,
            content = result.assistant_content,
            reasoning = rendered_reasoning,
            tool_calls = result.tool_calls,
            raw_metadata = result.raw_metadata,
        )

    def _handle_tool_calls(
        self,
        tool_calls: List[Dict],
        interactive: bool,
    ) -> List[Dict]:
        """
        Execute tool calls and return tool result messages.

        Parameters:
            tool_calls: Tool call list from model.
            interactive: Whether to allow interactive reasoning expansion.
        """
        tool_results = []
        for tool_call in tool_calls:
            function_block = tool_call.get("function") or {}
            tool_name = function_block.get("name")
            args = _parse_tool_args(function_block.get("arguments"))
            output, error = self._safe_call_tool(
                tool_name = tool_name,
                args = args,
                interactive = interactive,
            )
            if error:
                output = {"error": error}
            self.session.record_tool(
                actor = self.actor,
                tool_name = tool_name or "unknown",
                arguments = args,
                output = output,
            )
            tool_results.append(
                _format_tool_result(
                    tool_call_id = tool_call.get("id"),
                    tool_name = tool_name,
                    output = output,
                    context_manager = self.context_manager,
                )
            )
        return tool_results

    def _safe_call_tool(
        self,
        tool_name: str,
        args: Dict,
        interactive: bool,
    ) -> Tuple[Dict, Optional[str]]:
        """
        Execute a tool call with exception protection.

        Parameters:
            tool_name: Tool function name.
            args: Parsed tool argument dict.
            interactive: Whether to allow interactive reasoning expansion.
        """
        try:
            return self._execute_tool_call(
                tool_name = tool_name,
                args = args,
                interactive = interactive,
            ), None
        except TypeError as exc:
            return {}, f"Tool '{tool_name}' argument error: {exc}"
        except Exception as exc:
            return {}, f"Tool '{tool_name}' runtime error: {exc}"

    def _execute_tool_call(
        self,
        tool_name: str,
        args: Dict,
        interactive: bool,
    ) -> Dict:
        """
        Execute a tool by name and return a JSON-serializable dict.

        Parameters:
            tool_name: Tool function name.
            args: Parsed tool argument dict.
            interactive: Whether to allow interactive reasoning expansion.
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
            summary = self.run_subagent(
                description = description,
                prompt = prompt,
                agent_type = agent_type,
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
            if skill_name not in self.skills_used:
                self.skills_used.append(skill_name)
            return {"content": content, "skill_name": skill_name}

        return {"error": f"Unknown tool: {tool_name}"}


def parse_args():
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description = "Compression Agent - Chat with LLM and use tools"
    )
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
    Main function to run the compression agent from command line.
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

    agent = Agent(
        runtime_options = runtime_options,
        trace_logger = tracer,
        session_store = session,
        context_manager = CTX,
    )

    if args.prompt:
        logger.info("=" * 80)
        logger.info("Starting Compression Agent in single-shot mode")
        logger.info("=" * 80)

        try:
            result = agent.run(
                prompt = args.prompt,
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
        logger.info("Starting Compression Agent in interactive mode")
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

                result = agent.run(
                    prompt = prompt,
                    history = history,
                    interactive = True,
                )
                history = agent.history
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
