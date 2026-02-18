"""Unit tests for reasoning preview, folding, and expansion flow."""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import run_tests
from utils.reasoning_renderer import ReasoningRenderer


def test_stream_preview_truncation():
    """Stream preview should truncate to configured chars and show folded notice."""
    output = io.StringIO()
    renderer = ReasoningRenderer(
        preview_chars = 5,
        output_stream = output,
        input_func = lambda prompt: "",
    )

    renderer.handle_stream_chunk("abcdef")
    result = renderer.finalize_turn(
        full_reasoning = "abcdef",
        stream_mode = True,
        allow_expand_prompt = False,
        interactive = False,
    )

    rendered = output.getvalue()
    assert "[Reasoning Preview]" in rendered
    assert "abcde" in rendered
    assert "[Reasoning Folded]" in rendered
    assert result["folded"] is True

    print("PASS: test_stream_preview_truncation")
    return True


def test_expand_content_consistency():
    """Expanded reasoning should match the buffered full reasoning text."""
    output = io.StringIO()
    renderer = ReasoningRenderer(
        preview_chars = 3,
        output_stream = output,
        input_func = lambda prompt: "r",
    )

    renderer.handle_stream_chunk("hello")
    result = renderer.finalize_turn(
        full_reasoning = "hello",
        stream_mode = True,
        allow_expand_prompt = True,
        interactive = True,
    )

    rendered = output.getvalue()
    assert result["expanded"] is True
    assert "[Reasoning Expanded]" in rendered
    assert "hello" in rendered

    print("PASS: test_expand_content_consistency")
    return True


def test_non_stream_expand_hint():
    """Non-stream mode should show reasoning-available hint."""
    output = io.StringIO()
    renderer = ReasoningRenderer(
        preview_chars = 20,
        output_stream = output,
        input_func = lambda prompt: "",
    )

    result = renderer.finalize_turn(
        full_reasoning = "short reasoning",
        stream_mode = False,
        allow_expand_prompt = False,
        interactive = False,
    )

    rendered = output.getvalue()
    assert result["has_reasoning"] is True
    assert "Reasoning Available" in rendered

    print("PASS: test_non_stream_expand_hint")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_stream_preview_truncation,
        test_expand_content_consistency,
        test_non_stream_expand_hint,
    ]) else 1)
