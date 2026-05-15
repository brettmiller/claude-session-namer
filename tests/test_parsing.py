import json
import pytest
import session_namer as sn


def write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def user_entry(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def asst_entry(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": text}}


class TestParseTranscript:
    def test_returns_messages_when_no_title(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [user_entry("Hello"), asst_entry("World")])
        user_msgs, asst_msgs, has_title = sn.parse_transcript(str(f))
        assert user_msgs == ["Hello"]
        assert asst_msgs == ["World"]
        assert not has_title

    def test_detects_custom_title(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            user_entry("Hello"), asst_entry("World"),
            {"type": "custom-title", "customTitle": "my-title", "sessionId": "abc"},
        ])
        _, _, has_title = sn.parse_transcript(str(f))
        assert has_title

    def test_does_not_detect_ai_title_as_named(self, tmp_path):
        # ai-title is NOT "has_title" — Claude Code writes ai-title before the hook fires,
        # so treating it as "already named" would prevent our hook from ever running.
        # ai-title IS used by _read_session_title to build the avoid set, not to skip.
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            user_entry("Hello"), asst_entry("World"),
            {"type": "ai-title", "aiTitle": "Analyze something", "sessionId": "abc"},
        ])
        _, _, has_title = sn.parse_transcript(str(f))
        assert not has_title

    def test_detects_custom_title_even_when_ai_title_present(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            user_entry("Hello"), asst_entry("World"),
            {"type": "ai-title", "aiTitle": "ai-name"},
            {"type": "custom-title", "customTitle": "custom-name"},
        ])
        _, _, has_title = sn.parse_transcript(str(f))
        assert has_title

    def test_filters_angle_bracket_system_messages(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            user_entry("<system>context</system>"),
            user_entry("Real question"),
            asst_entry("Answer"),
        ])
        user_msgs, _, _ = sn.parse_transcript(str(f))
        assert user_msgs == ["Real question"]

    def test_filters_slash_commands(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            user_entry("/help"),
            user_entry("Real question"),
            asst_entry("Answer"),
        ])
        user_msgs, _, _ = sn.parse_transcript(str(f))
        assert user_msgs == ["Real question"]

    def test_empty_file(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("")
        user_msgs, asst_msgs, has_title = sn.parse_transcript(str(f))
        assert user_msgs == []
        assert asst_msgs == []
        assert not has_title

    def test_missing_file(self, tmp_path):
        user_msgs, asst_msgs, has_title = sn.parse_transcript(str(tmp_path / "missing.jsonl"))
        assert user_msgs == []
        assert asst_msgs == []
        assert not has_title

    def test_list_content_format(self, tmp_path):
        # Real Claude Code messages use list content: [{"type": "text", "text": "..."}]
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "Hello from list"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "World from list"}]}},
        ])
        user_msgs, asst_msgs, _ = sn.parse_transcript(str(f))
        assert user_msgs == ["Hello from list"]
        assert asst_msgs == ["World from list"]

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("\n" + json.dumps(user_entry("Hello")) + "\n\n" + json.dumps(asst_entry("World")) + "\n")
        user_msgs, asst_msgs, _ = sn.parse_transcript(str(f))
        assert user_msgs == ["Hello"]
        assert asst_msgs == ["World"]

    def test_skips_invalid_json_lines(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("not json\n" + json.dumps(user_entry("Hello")) + "\n" + json.dumps(asst_entry("World")) + "\n")
        user_msgs, asst_msgs, _ = sn.parse_transcript(str(f))
        assert user_msgs == ["Hello"]
        assert asst_msgs == ["World"]


class TestReadSessionTitle:
    def test_reads_custom_title(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [{"type": "custom-title", "customTitle": "my-custom-title"}])
        assert sn._read_session_title(str(f)) == "my-custom-title"

    def test_reads_ai_title(self, tmp_path):
        # Regression: _read_custom_title only read custom-title, ignoring ai-title
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [{"type": "ai-title", "aiTitle": "my-ai-title"}])
        assert sn._read_session_title(str(f)) == "my-ai-title"

    def test_prefers_custom_over_ai(self, tmp_path):
        # Regression: ai-title was not considered at all
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "ai-title", "aiTitle": "ai-name"},
            {"type": "custom-title", "customTitle": "custom-name"},
        ])
        assert sn._read_session_title(str(f)) == "custom-name"

    def test_returns_none_when_neither(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [user_entry("hello")])
        assert sn._read_session_title(str(f)) is None

    def test_skips_invalid_json_lines(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text("not json\n" + json.dumps({"type": "custom-title", "customTitle": "my-title"}) + "\n")
        assert sn._read_session_title(str(f)) == "my-title"

    def test_returns_none_for_missing_file(self, tmp_path):
        assert sn._read_session_title(str(tmp_path / "missing.jsonl")) is None


class TestTextFromContent:
    def test_string_passthrough(self):
        assert sn._text_from_content("hello") == "hello"

    def test_list_with_text_block(self):
        # Real Claude Code messages use list content: [{"type": "text", "text": "..."}]
        assert sn._text_from_content([{"type": "text", "text": "hello from list"}]) == "hello from list"

    def test_list_skips_non_text_blocks_before_text(self):
        content = [{"type": "tool_use", "name": "bash"}, {"type": "text", "text": "found it"}]
        assert sn._text_from_content(content) == "found it"

    def test_list_returns_empty_when_no_text_block(self):
        assert sn._text_from_content([{"type": "tool_use", "name": "bash"}]) == ""

    def test_non_list_non_string_returns_empty(self):
        assert sn._text_from_content(None) == ""
        assert sn._text_from_content(42) == ""


class TestNormalizeTitle:
    def test_valid_title_passthrough(self):
        assert sn._normalize_title("fix-stripe-webhook-retry") == "fix-stripe-webhook-retry"

    def test_too_short_returns_none(self):
        assert sn._normalize_title("abc-def") is None  # 7 chars < 10

    def test_too_long_returns_none(self):
        title = "abcde-" * 11  # 66 chars, > 60
        assert sn._normalize_title(title) is None

    def test_strips_quotes_and_backticks(self):
        assert sn._normalize_title('"fix-stripe-webhook-retry"') == "fix-stripe-webhook-retry"
        assert sn._normalize_title("`fix-stripe-webhook-retry`") == "fix-stripe-webhook-retry"

    def test_converts_spaces_to_hyphens(self):
        assert sn._normalize_title("fix stripe webhook retry") == "fix-stripe-webhook-retry"

    def test_converts_underscores_to_hyphens(self):
        assert sn._normalize_title("fix_stripe_webhook_retry") == "fix-stripe-webhook-retry"

    def test_lowercases(self):
        assert sn._normalize_title("Fix-Stripe-Webhook-Retry") == "fix-stripe-webhook-retry"

    def test_boundary_exactly_10_chars(self):
        assert sn._normalize_title("abcde-fghi") == "abcde-fghi"

    def test_boundary_exactly_60_chars(self):
        title = "ab-cd-ef-gh-ij-kl-mn-op-qr-st-uv-wx-yz-ab-cd-ef-gh-ij-klmnop"
        assert len(title) == 60, f"Expected 60, got {len(title)}"
        assert sn._normalize_title(title) == title

    def test_all_special_chars_returns_none(self):
        # After stripping non-alphanumeric chars, empty string fails the fullmatch regex check
        assert sn._normalize_title("!!!") is None


class TestBuildConversation:
    def test_labels_turns(self):
        result = sn._build_conversation(["user1", "user2"], ["asst1", "asst2"])
        assert "Turn 1 User: user1" in result
        assert "Turn 1 Assistant: asst1" in result
        assert "Turn 2 User: user2" in result
        assert "Turn 2 Assistant: asst2" in result

    def test_caps_at_4_turn_pairs(self):
        users = [f"user{i}" for i in range(10)]
        assts = [f"asst{i}" for i in range(10)]
        result = sn._build_conversation(users, assts)
        assert "Turn 4" in result
        assert "Turn 5" not in result

    def test_truncates_user_at_400_chars(self):
        result = sn._build_conversation(["x" * 500], ["short"])
        assert "x" * 400 in result
        assert "x" * 401 not in result

    def test_truncates_assistant_at_200_chars(self):
        result = sn._build_conversation(["short"], ["y" * 300])
        assert "y" * 200 in result
        assert "y" * 201 not in result
