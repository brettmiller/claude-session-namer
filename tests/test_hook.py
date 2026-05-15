import json
import os
import subprocess
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import session_namer as sn

SCRIPT = Path(__file__).parent.parent / "claude-session-namer"


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
    def test_run_hook_spawns_background_process(self, tmp_path):
        # Regression: run_hook was calling name_session synchronously, which calls
        # claude -p. That takes 10-20s and Claude Code kills the hook process before
        # it finishes, so custom-title was never written. run_hook must return
        # immediately and spawn naming in a detached background process.
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({"session_id": "abc123", "transcript_path": str(f)})
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "--name" in cmd
        assert "abc123" in cmd
        assert str(f) in cmd

    def test_uses_transcript_path_from_payload(self, tmp_path):
        # The SessionEnd payload provides transcript_path as an absolute path.
        # run_hook must pass it directly to the background process.
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({"session_id": "abc123", "transcript_path": str(f)})
        cmd = mock_popen.call_args[0][0]
        assert str(f) in cmd

    def test_uses_real_claude_code_payload(self, tmp_path):
        # Full payload format from Claude Code SessionEnd hook.
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({
                "session_id": "abc123def456",
                "transcript_path": str(f),
                "cwd": str(tmp_path),
                "hook_event_name": "SessionEnd",
                "reason": "prompt_input_exit",
            })
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "abc123def456" in cmd
        assert str(f) in cmd

    def test_skips_empty_data(self):
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({})
        mock_popen.assert_not_called()

    def test_skips_missing_file(self, tmp_path):
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({"session_id": "abc123", "transcript_path": str(tmp_path / "missing.jsonl")})
        mock_popen.assert_not_called()

    def test_skips_already_titled_session(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "custom-title", "customTitle": "existing-title"},
        ])
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({"session_id": "abc123", "transcript_path": str(f)})
        mock_popen.assert_not_called()

    def test_spawns_for_ai_titled_session(self, tmp_path):
        # Claude Code writes ai-title before firing the hook, so the hook must still
        # spawn naming for sessions that only have ai-title.
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "ai-title", "aiTitle": "existing-ai-title-here"},
        ])
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({"session_id": "abc123", "transcript_path": str(f)})
        mock_popen.assert_called_once()

    def test_skips_worker_session_path(self, tmp_path):
        # Regression: generate_title's claude -p creates a temp session whose project
        # key contains "claude-session-namer-" (temp prefix with trailing dash). When
        # that session ends, the hook must skip it to prevent infinite recursion.
        worker_proj = tmp_path / "-private-tmp-claude-session-namer-abc123"
        worker_proj.mkdir()
        f = worker_proj / "session.jsonl"
        make_session(f)
        with patch("subprocess.Popen") as mock_popen:
            sn.run_hook({"session_id": "abc123", "transcript_path": str(f)})
        mock_popen.assert_not_called()


class TestEntryPoint:
    def test_no_args_runs_hook_not_usage(self):
        # Claude Code invokes the script with NO args and JSON on stdin.
        # When args is empty the script must enter hook mode, not print usage.
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input="{}",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "Usage:" not in result.stdout


class TestGenerateTitle:
    def test_passes_skip_env_var_to_subprocess(self):
        # Regression: generate_title's claude -p session fires SessionEnd hook recursively.
        # Passing CLAUDE_SESSION_NAMER_SKIP=1 causes that hook invocation to exit
        # immediately, preventing infinite recursion.
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "fix-stripe-webhook-retry"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            sn.generate_title("some conversation")
        call_kwargs = mock_run.call_args.kwargs
        env = call_kwargs.get("env", {})
        assert env.get("CLAUDE_SESSION_NAMER_SKIP") == "1"

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
