import json
import pytest
from unittest.mock import patch
import session_namer as sn


class TestStatus:
    def test_detects_installed_hook(self, tmp_path, capsys):
        settings = {"hooks": {"SessionEnd": [
            {"hooks": [{"type": "command", "command": "/path/to/claude-session-namer"}]}
        ]}}
        f = tmp_path / "settings.json"
        f.write_text(json.dumps(settings))
        with patch.object(sn, "SETTINGS_FILE", f):
            sn.status()
        assert "Installed" in capsys.readouterr().out

    def test_reports_not_installed_when_empty(self, tmp_path, capsys):
        f = tmp_path / "settings.json"
        f.write_text("{}")
        with patch.object(sn, "SETTINGS_FILE", f):
            sn.status()
        assert "Not installed" in capsys.readouterr().out

    def test_detects_hyphen_spelling(self, tmp_path, capsys):
        # Regression: old code checked "session_namer" (underscore) not "claude-session-namer" (hyphen)
        settings = {"hooks": {"SessionEnd": [
            {"hooks": [{"type": "command", "command": "/path/to/claude-session-namer"}]}
        ]}}
        f = tmp_path / "settings.json"
        f.write_text(json.dumps(settings))
        with patch.object(sn, "SETTINGS_FILE", f):
            sn.status()
        assert "Installed" in capsys.readouterr().out

    def test_does_not_detect_underscore_spelling(self, tmp_path, capsys):
        # The hook command uses a hyphen; underscore should not match
        settings = {"hooks": {"SessionEnd": [
            {"hooks": [{"type": "command", "command": "/path/to/claude_session_namer"}]}
        ]}}
        f = tmp_path / "settings.json"
        f.write_text(json.dumps(settings))
        with patch.object(sn, "SETTINGS_FILE", f):
            sn.status()
        assert "Not installed" in capsys.readouterr().out


class TestHelpFlag:
    def test_help_detected_in_any_position(self):
        # Regression: old code only checked args[0]
        cases = [
            ["--help"],
            ["-h"],
            ["backfill", "--help"],
            ["--help", "backfill"],
            ["install", "-h"],
        ]
        for args in cases:
            assert "--help" in args or "-h" in args


class TestCwdProjectDir:
    def test_key_starts_with_dash(self):
        # Regression: lstrip("/") produced "Users-Brett-Miller-..." instead of "-Users-Brett-Miller-..."
        result = sn._cwd_project_dir()
        assert result.name.startswith("-"), (
            f"Project dir key should start with '-' (from leading '/'), got: {result.name}"
        )
