"""Unit tests for thinking policy detection and fallback behavior."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import run_tests
from utils.llm_call import call_chat_completion
from utils.thinking_policy import build_thinking_params, resolve_thinking_policy


class _FakeMessage:
    """Simple fake assistant message payload."""

    def __init__(self, content = "ok"):
        self.content = content
        self.tool_calls = None


class _FakeChoice:
    """Simple fake choice wrapper."""

    def __init__(self, message):
        self.message = message


class _FakeResponse:
    """Simple fake response object compatible with llm_call helper."""

    def __init__(self, content = "ok"):
        self.choices = [_FakeChoice(_FakeMessage(content = content))]
        self.id = "fake-id"
        self.model = "fake-model"
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1}

    def model_dump(self):
        """Return serializable representation."""
        return {
            "id": self.id,
            "model": self.model,
        }


class _ProbeClient:
    """Fake client for capability probe testing."""

    def __init__(self, mode):
        self.mode = mode
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        """Simulate support matrix by mode + thinking params."""
        enabled = kwargs.get("enable_thinking")
        effort = kwargs.get("reasoning_effort")

        if self.mode == "toggle":
            if enabled in {True, False}:
                return _FakeResponse()
            if effort in {"none", "low", "medium", "high"}:
                return _FakeResponse()
            return _FakeResponse()

        if self.mode == "always":
            if enabled is True:
                return _FakeResponse()
            raise RuntimeError("enable_thinking=False is not supported")

        if self.mode == "never":
            if enabled is not None or effort is not None:
                raise RuntimeError("unknown parameter enable_thinking")
            return _FakeResponse()

        raise RuntimeError("invalid fake mode")


def test_auto_capability_resolution():
    """Auto detection should identify toggle/always/never capability."""
    toggle_policy = resolve_thinking_policy(
        client = _ProbeClient("toggle"),
        model = "fake-model",
        capability_setting = "auto",
        param_style_setting = "enable_thinking",
    )
    assert toggle_policy.capability == "toggle"

    always_policy = resolve_thinking_policy(
        client = _ProbeClient("always"),
        model = "fake-model",
        capability_setting = "auto",
        param_style_setting = "enable_thinking",
    )
    assert always_policy.capability == "always"

    never_policy = resolve_thinking_policy(
        client = _ProbeClient("never"),
        model = "fake-model",
        capability_setting = "auto",
        param_style_setting = "enable_thinking",
    )
    assert never_policy.capability == "never"

    print("PASS: test_auto_capability_resolution")
    return True


def test_build_thinking_params_matrix():
    """Policy + mode combinations should emit expected request params."""
    toggle_policy = resolve_thinking_policy(
        client = _ProbeClient("toggle"),
        model = "fake-model",
        capability_setting = "auto",
        param_style_setting = "enable_thinking",
    )

    assert build_thinking_params(toggle_policy, "on", "high") == {"enable_thinking": True}
    assert build_thinking_params(toggle_policy, "off", "high") == {"enable_thinking": False}
    assert build_thinking_params(toggle_policy, "auto", "high") == {}

    always_policy = resolve_thinking_policy(
        client = _ProbeClient("always"),
        model = "fake-model",
        capability_setting = "auto",
        param_style_setting = "enable_thinking",
    )
    assert build_thinking_params(always_policy, "auto", "low") == {"enable_thinking": True}

    never_policy = resolve_thinking_policy(
        client = _ProbeClient("never"),
        model = "fake-model",
        capability_setting = "auto",
        param_style_setting = "enable_thinking",
    )
    assert build_thinking_params(never_policy, "on", "high") == {}

    print("PASS: test_build_thinking_params_matrix")
    return True


def test_thinking_param_retry_fallback():
    """LLM call should retry once without unsupported thinking params."""

    class _RetryClient:
        def __init__(self):
            self.chat = self
            self.completions = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if "enable_thinking" in kwargs:
                raise RuntimeError("unknown parameter enable_thinking")
            return _FakeResponse(content = "retry_ok")

    client = _RetryClient()
    result = call_chat_completion(
        client = client,
        model = "fake-model",
        messages = [{"role": "user", "content": "hi"}],
        tools = None,
        max_tokens = 16,
        stream = False,
        thinking_params = {"enable_thinking": True},
    )

    assert client.calls == 2, f"Expected retry call count 2, got {client.calls}"
    assert result.assistant_content == "retry_ok"
    assert result.raw_metadata.get("thinking_params_stripped_retry") is True

    print("PASS: test_thinking_param_retry_fallback")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_auto_capability_resolution,
        test_build_thinking_params_matrix,
        test_thinking_param_retry_fallback,
    ]) else 1)
