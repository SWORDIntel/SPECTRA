"""
Unit tests for L5 formatting fingerprint feature extraction.

Tests:
- Empty input returns defaults
- Messages without text return defaults
- JSON serializability of output
- Markdown formatting (bold, italic, code, codeblocks, blockquotes, headings)
- Lists, paragraphs, and blank line detection
- Shell commands, paths, environment variables, URLs
- Colon and semicolon context distributions
- Dash type distributions
- Scalar ranges and distribution capping
"""
from __future__ import annotations

import json
import pytest

from tgarchive.intelligence.features.formatting import (
    DEFAULT_FORMATTING_FEATURES,
    extract_formatting_features,
)


class TestFormattingFeatures:
    """Tests for formatting feature extraction."""

    def test_empty_messages(self):
        feat = extract_formatting_features([])
        assert isinstance(feat, dict)
        assert feat["paragraph_count"] == 0
        assert feat["paragraph_length_distribution"]["mean"] == 0.0
        assert feat["blank_line_rate"] == 0.0
        assert feat["bold_rate"] == 0.0
        assert feat["codeblock_rate"] == 0.0
        assert feat["code_language_distribution"] == {}
        assert feat["colon_usage_context"] == {}
        assert feat["dash_type_distribution"] == {}

    def test_messages_without_text(self):
        feat = extract_formatting_features([
            {"id": 100},
            {"date": "2026-01-01"},
            {"content": None},
            {"text": ""},
        ])
        assert feat["paragraph_count"] == 0
        assert feat["bold_rate"] == 0.0
        assert feat["url_rate"] == 0.0

    def test_json_serializable(self):
        messages = [
            {
                "content": (
                    "# Title\n\n"
                    "This is **bold** and *italic* text with `code`.\n\n"
                    "```python\n"
                    "def foo():\n"
                    "    return 42\n"
                    "```\n\n"
                    "- Item 1\n"
                    "- Item 2\n\n"
                    "> A quote here\n\n"
                    "Run `$ python3 script.py` at `/usr/local/bin` using `$PORT`.\n"
                    "See https://example.com/doc."
                )
            }
        ]
        feat = extract_formatting_features(messages)
        serialized = json.dumps(feat)
        assert isinstance(serialized, str)
        deserialized = json.loads(serialized)
        assert deserialized["paragraph_count"] > 0
        assert "python" in deserialized["code_language_distribution"]

    def test_markdown_inline_and_blocks(self):
        messages = [
            {
                "content": (
                    "Here is **bold text** and __also bold__.\n"
                    "Here is *italic text* and _also italic_.\n"
                    "Use `inline_command` for testing.\n"
                    "```bash\n"
                    "echo 'hello world'\n"
                    "```\n"
                    "# Main Heading\n"
                    "## Sub Heading\n"
                    "> Important warning quote\n"
                )
            }
        ]
        feat = extract_formatting_features(messages)
        assert feat["bold_rate"] >= 1.0
        assert feat["italic_rate"] >= 1.0
        assert feat["inline_code_rate"] >= 1.0
        assert feat["codeblock_rate"] >= 1.0
        assert feat["markdown_heading_rate"] > 0.0
        assert feat["blockquote_rate"] > 0.0
        assert "bash" in feat["code_language_distribution"]
        assert feat["code_language_distribution"]["bash"] == pytest.approx(1.0, 0.01)

    def test_lists_and_paragraphs(self):
        messages = [
            {
                "content": (
                    "Paragraph one with some text.\n\n"
                    "Paragraph two with a list:\n"
                    "- Bullet one\n"
                    "* Bullet two\n"
                    "• Bullet three\n"
                    "· Bullet four\n\n"
                    "Paragraph three with numbered list:\n"
                    "1. First step\n"
                    "2. Second step\n"
                    "3) Third step\n\n"
                    "Final paragraph.\n"
                )
            }
        ]
        feat = extract_formatting_features(messages)
        assert feat["paragraph_count"] >= 4
        assert feat["paragraph_length_distribution"]["mean"] > 0
        assert feat["paragraph_length_distribution"]["min"] > 0
        assert feat["paragraph_length_distribution"]["max"] >= feat["paragraph_length_distribution"]["min"]
        assert feat["bullet_usage_rate"] > 0.0
        assert feat["numbered_list_rate"] > 0.0
        assert feat["blank_line_rate"] > 0.0

    def test_shell_commands_paths_and_env_vars(self):
        messages = [
            {
                "content": (
                    "$ cd /var/log/nginx\n"
                    "$ sudo systemctl restart nginx\n"
                    "export API_KEY=secret\n"
                    "Check config at ~/.config/app/settings.json\n"
                    "Set ${PORT} and $DEBUG_MODE.\n"
                    "Visit https://api.threatintel.org/v1/feed\n"
                )
            }
        ]
        feat = extract_formatting_features(messages)
        assert feat["shell_command_rate"] > 0.0
        assert feat["inline_path_rate"] > 0.0
        assert feat["environment_variable_rate"] > 0.0
        assert feat["url_rate"] > 0.0

    def test_colon_and_semicolon_contexts(self):
        messages = [
            {
                "content": (
                    "Time: 14:30 UTC\n"
                    "Note: Remember to verify the hash\n"
                    "scope::function_call();\n"
                    "int x = 10;\n"
                    "Good job ;) see you;\n"
                )
            }
        ]
        feat = extract_formatting_features(messages)
        assert "in_time" in feat["colon_usage_context"] or "after_word" in feat["colon_usage_context"]
        assert len(feat["semicolon_usage_context"]) > 0

    def test_dash_type_distribution(self):
        messages = [
            {
                "content": "Option-A - option-B — em-dash -- double-dash – en-dash"
            }
        ]
        feat = extract_formatting_features(messages)
        dash_dist = feat["dash_type_distribution"]
        assert len(dash_dist) >= 3
        assert sum(dash_dist.values()) == pytest.approx(1.0, 0.01)

    def test_newline_after_punctuation(self):
        messages = [
            {"content": "First line.\nSecond line.\nThird line."},
            {"content": "Sentence one. Sentence two. Sentence three."},
        ]
        feat = extract_formatting_features(messages)
        assert 0.0 <= feat["newline_after_punctuation_rate"] <= 1.0

    def test_scalars_valid_and_distributions_capped(self):
        # Generate varied formatting text
        messages = [
            {"content": f"Message {i}: **bold** `code_{i}` at /path/{i} with $VAR_{i}"}
            for i in range(30)
        ]
        feat = extract_formatting_features(messages)
        assert feat["paragraph_count"] == 30
        assert 0.0 <= feat["blank_line_rate"] <= 1.0
        assert 0.0 <= feat["bullet_usage_rate"] <= 1.0
        assert 0.0 <= feat["numbered_list_rate"] <= 1.0
        assert 0.0 <= feat["markdown_heading_rate"] <= 1.0
        assert 0.0 <= feat["blockquote_rate"] <= 1.0
        assert 0.0 <= feat["shell_command_rate"] <= 1.0
        assert 0.0 <= feat["newline_after_punctuation_rate"] <= 1.0
        assert feat["bold_rate"] >= 0.0
        assert feat["inline_code_rate"] >= 0.0
        assert feat["inline_path_rate"] >= 0.0
        assert feat["environment_variable_rate"] >= 0.0
        assert len(feat["code_language_distribution"]) <= 20
        assert len(feat["dash_type_distribution"]) <= 50
        assert len(feat["colon_usage_context"]) <= 50
        assert len(feat["semicolon_usage_context"]) <= 50
