import json
import subprocess
import sys
import pytest
from pathlib import Path
from unittest.mock import patch
import session_namer as sn

SCRIPT = Path(__file__).parent.parent / "claude-session-namer"


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


class TestUnknownCommand:
    def test_unknown_command_exits_nonzero_with_error(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--backfill"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        assert "Error: unknown command" in result.stderr
        assert "Usage:" in result.stderr


class TestHelpFlag:
    def test_help_detected_in_any_position(self):
        # Regression: old code only checked args[0], so "backfill --help" didn't show usage.
        for args in [["--help"], ["-h"], ["backfill", "--help"], ["install", "-h"]]:
            result = subprocess.run(
                [sys.executable, str(SCRIPT)] + args,
                capture_output=True, text=True, timeout=10,
            )
            assert "Usage:" in result.stdout, f"Expected 'Usage:' for args {args}"


class TestLoadSettings:
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        with patch.object(sn, "SETTINGS_FILE", tmp_path / "missing.json"):
            assert sn._load_settings() == {}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path):
        f = tmp_path / "settings.json"
        f.write_text("not valid {{{ json")
        with patch.object(sn, "SETTINGS_FILE", f):
            assert sn._load_settings() == {}


class TestInstall:
    def test_installs_hook(self, tmp_path, capsys):
        f = tmp_path / "settings.json"
        f.write_text("{}")
        with patch.object(sn, "SETTINGS_FILE", f):
            with patch.object(sn, "SCRIPT_PATH", Path("/usr/local/bin/claude-session-namer")):
                sn.install()
        settings = json.loads(f.read_text())
        commands = [hh["command"] for h in settings["hooks"]["SessionEnd"] for hh in h.get("hooks", [])]
        assert any("claude-session-namer" in c for c in commands)
        assert "Installed" in capsys.readouterr().out

    def test_deduplicates_stale_entry(self, tmp_path):
        settings = {"hooks": {"SessionEnd": [
            {"hooks": [{"type": "command", "command": "/old/path/claude-session-namer"}]}
        ]}}
        f = tmp_path / "settings.json"
        f.write_text(json.dumps(settings))
        with patch.object(sn, "SETTINGS_FILE", f):
            with patch.object(sn, "SCRIPT_PATH", Path("/new/path/claude-session-namer")):
                sn.install()
        settings = json.loads(f.read_text())
        commands = [hh["command"] for h in settings["hooks"]["SessionEnd"] for hh in h.get("hooks", [])]
        assert len(commands) == 1
        assert "/new/path" in commands[0]

    def test_creates_settings_file_when_missing(self, tmp_path, capsys):
        f = tmp_path / "settings.json"
        with patch.object(sn, "SETTINGS_FILE", f):
            with patch.object(sn, "SCRIPT_PATH", Path("/usr/local/bin/claude-session-namer")):
                sn.install()
        assert f.exists()
        assert "Installed" in capsys.readouterr().out


class TestUninstall:
    def test_removes_hook_and_cleans_up_keys(self, tmp_path, capsys):
        settings = {"hooks": {"SessionEnd": [
            {"hooks": [{"type": "command", "command": "/path/to/claude-session-namer"}]}
        ]}}
        f = tmp_path / "settings.json"
        f.write_text(json.dumps(settings))
        with patch.object(sn, "SETTINGS_FILE", f):
            sn.uninstall()
        result = json.loads(f.read_text())
        assert "hooks" not in result
        assert "Uninstalled" in capsys.readouterr().out

    def test_leaves_other_hooks_intact(self, tmp_path):
        settings = {"hooks": {"SessionEnd": [
            {"hooks": [{"type": "command", "command": "/path/to/claude-session-namer"}]},
            {"hooks": [{"type": "command", "command": "/path/to/other-hook"}]},
        ]}}
        f = tmp_path / "settings.json"
        f.write_text(json.dumps(settings))
        with patch.object(sn, "SETTINGS_FILE", f):
            sn.uninstall()
        result = json.loads(f.read_text())
        remaining = result["hooks"]["SessionEnd"]
        assert len(remaining) == 1
        assert "other-hook" in remaining[0]["hooks"][0]["command"]

    def test_uninstall_when_not_installed(self, tmp_path, capsys):
        f = tmp_path / "settings.json"
        f.write_text("{}")
        with patch.object(sn, "SETTINGS_FILE", f):
            sn.uninstall()
        assert "Uninstalled" in capsys.readouterr().out


class TestCwdProjectDir:
    def test_key_starts_with_dash(self):
        # Regression: lstrip("/") produced "Users-Brett-Miller-..." instead of "-Users-Brett-Miller-..."
        result = sn._cwd_project_dir()
        assert result.name.startswith("-"), (
            f"Project dir key should start with '-' (from leading '/'), got: {result.name}"
        )

    def test_key_replaces_dots_with_dashes(self):
        # Regression: only '/' was replaced; dots in path components (Brett.Miller, github.com)
        # were preserved, producing a key that never matches the real Claude project directory.
        from pathlib import Path
        from unittest.mock import patch
        fake_cwd = Path("/Users/Brett.Miller/code/github.com/myproject")
        with patch.object(Path, "cwd", return_value=fake_cwd):
            result = sn._cwd_project_dir()
        assert result.name == "-Users-Brett-Miller-code-github-com-myproject", result.name
