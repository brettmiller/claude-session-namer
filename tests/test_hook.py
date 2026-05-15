import json
import pytest
from unittest.mock import patch, MagicMock
import session_namer as sn


def write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def make_session(path, user_text="What is Python", asst_text="Python is a programming language"):
    write_jsonl(path, [
        {"type": "user", "message": {"role": "user", "content": user_text}},
        {"type": "assistant", "message": {"role": "assistant", "content": asst_text}},
    ])


class TestRunHook:
    def test_skips_empty_data(self, capsys):
        sn.run_hook({})
        assert capsys.readouterr().out == ""

    def test_skips_missing_file(self, capsys):
        sn.run_hook({"session_id": "abc", "transcript_path": "/nonexistent/path.jsonl"})
        assert capsys.readouterr().out == ""

    def test_skips_already_titled_session(self, tmp_path, capsys):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "custom-title", "customTitle": "existing-title"},
        ])
        with patch.object(sn, "generate_title") as mock_gen:
            sn.run_hook({"session_id": "abc", "transcript_path": str(f)})
        mock_gen.assert_not_called()
        assert capsys.readouterr().out == ""

    def test_skips_ai_titled_session(self, tmp_path, capsys):
        # Regression: ai-titled sessions were processed as untitled in hook mode too
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "ai-title", "aiTitle": "existing-ai-title-here"},
        ])
        with patch.object(sn, "generate_title") as mock_gen:
            sn.run_hook({"session_id": "abc", "transcript_path": str(f)})
        mock_gen.assert_not_called()
        assert capsys.readouterr().out == ""

    def test_outputs_system_message_json(self, tmp_path, capsys):
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", return_value="python-language-overview"):
            sn.run_hook({"session_id": "abc123", "transcript_path": str(f)})
        out = capsys.readouterr().out.strip()
        assert json.loads(out) == {"systemMessage": "Session named: python-language-overview"}

    def test_no_output_when_generate_fails(self, tmp_path, capsys):
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", return_value=None):
            sn.run_hook({"session_id": "abc", "transcript_path": str(f)})
        assert capsys.readouterr().out == ""


class TestGenerateTitle:
    def test_logs_stderr_on_nonzero_exit(self, capsys):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "authentication error"
        with patch("subprocess.run", return_value=mock_result):
            result = sn.generate_title("some conversation")
        assert result is None
        assert "claude -p failed" in capsys.readouterr().err

    def test_logs_stderr_on_exception(self, capsys):
        with patch("subprocess.run", side_effect=FileNotFoundError("claude not found")):
            result = sn.generate_title("some conversation")
        assert result is None
        assert "title generation error" in capsys.readouterr().err

    def test_returns_none_when_output_invalid(self):
        # _normalize_title rejects titles shorter than 10 chars
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "too-short"
        with patch("subprocess.run", return_value=mock_result):
            result = sn.generate_title("some conversation")
        assert result is None

    def test_normalizes_title_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Fix Stripe Webhook Retry"
        with patch("subprocess.run", return_value=mock_result):
            result = sn.generate_title("some conversation")
        assert result == "fix-stripe-webhook-retry"
