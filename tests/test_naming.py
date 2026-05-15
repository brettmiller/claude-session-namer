import json
import pytest
from unittest.mock import patch
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


class TestNameSession:
    def test_skips_session_with_custom_title(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "custom-title", "customTitle": "existing-title"},
        ])
        with patch.object(sn, "generate_title") as mock_gen:
            result = sn.name_session("abc", str(f))
        assert result is None
        mock_gen.assert_not_called()

    def test_names_session_with_only_ai_title(self, tmp_path):
        # Claude Code writes ai-title BEFORE firing the SessionEnd hook, so a session with
        # only ai-title is still "untitled" from our tool's perspective. We must name it.
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "ai-title", "aiTitle": "Analyze programming languages"},
        ])
        with patch.object(sn, "generate_title", return_value="analyze-programming-here"):
            result = sn.name_session("abc", str(f))
        assert result == "analyze-programming-here"
        assert '"custom-title"' in f.read_text()

    def test_names_untitled_session(self, tmp_path):
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", return_value="python-language-overview") as mock_gen:
            result = sn.name_session("abc123", str(f))
        assert result == "python-language-overview"
        content = f.read_text()
        assert '"custom-title"' in content
        assert "python-language-overview" in content
        # Verify _build_conversation output reaches generate_title
        conversation_arg = mock_gen.call_args.args[0]
        assert "Turn 1 User:" in conversation_arg
        assert "What is Python" in conversation_arg

    def test_returns_none_when_generate_fails(self, tmp_path):
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", return_value=None):
            result = sn.name_session("abc", str(f))
        assert result is None
        assert '"custom-title"' not in f.read_text()

    def test_retries_when_title_duplicates_custom_title(self, tmp_path):
        # Regression: duplicates were written without retry
        sibling = tmp_path / "existing.jsonl"
        write_jsonl(sibling, [{"type": "custom-title", "customTitle": "duplicate-title-name"}])
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", side_effect=["duplicate-title-name", "unique-title-here"]):
            result = sn.name_session("abc", str(f))
        assert result == "unique-title-here"

    def test_retries_when_title_duplicates_ai_title(self, tmp_path):
        # Regression: ai-title values were not in the avoid set
        sibling = tmp_path / "existing.jsonl"
        write_jsonl(sibling, [{"type": "ai-title", "aiTitle": "existing-ai-title-name"}])
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", side_effect=["existing-ai-title-name", "unique-title-here"]):
            result = sn.name_session("abc", str(f))
        assert result == "unique-title-here"

    def test_normalizes_ai_title_in_avoid_set(self, tmp_path):
        # Regression: aiTitle is natural-language; avoid comparison was always False against
        # normalized generated titles, so duplicates of ai-titled sessions were written.
        sibling = tmp_path / "existing.jsonl"
        write_jsonl(sibling, [{"type": "ai-title", "aiTitle": "Analyze Programming Languages"}])
        f = tmp_path / "s.jsonl"
        make_session(f)
        # model generates the normalized form of the ai-title
        with patch.object(sn, "generate_title", side_effect=["analyze-programming-languages", "unique-title-here"]):
            result = sn.name_session("abc", str(f))
        assert result == "unique-title-here"

    def test_falls_back_to_suffix_when_retry_still_duplicates(self, tmp_path):
        sibling = tmp_path / "existing.jsonl"
        write_jsonl(sibling, [{"type": "custom-title", "customTitle": "duplicate-title-name"}])
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", return_value="duplicate-title-name"):
            result = sn.name_session("abc", str(f))
        assert result == "duplicate-title-name-2"

    def test_returns_none_when_no_user_messages(self, tmp_path):
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "/help"}},  # filtered as system
            {"type": "assistant", "message": {"role": "assistant", "content": "Here is help"}},
        ])
        with patch.object(sn, "generate_title") as mock_gen:
            result = sn.name_session("abc", str(f))
        assert result is None
        mock_gen.assert_not_called()

    def test_logs_stderr_on_exception(self, tmp_path, capsys):
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", side_effect=RuntimeError("unexpected error")):
            result = sn.name_session("abc12345", str(f))
        assert result is None
        assert "naming failed" in capsys.readouterr().err


class TestDeduplicateWithRegen:
    def test_no_duplicates_unchanged(self):
        proposed = [
            ("a", "/a.jsonl", "title-one-here"),
            ("b", "/b.jsonl", "title-two-here"),
        ]
        with patch.object(sn, "generate_title"):
            result = sn._deduplicate_with_regen(proposed, {}, "haiku", set())
        assert [(s, p, t) for s, p, t in result] == proposed

    def test_duplicate_regenerated_to_unique(self):
        proposed = [
            ("a", "/a.jsonl", "same-title-here"),
            ("b", "/b.jsonl", "same-title-here"),
        ]
        with patch.object(sn, "generate_title", return_value="unique-new-title"):
            result = sn._deduplicate_with_regen(proposed, {"b": (["q"], ["a"])}, "haiku", set())
        titles = [t for _, _, t in result]
        assert "same-title-here" in titles
        assert "unique-new-title" in titles

    def test_duplicate_falls_back_to_suffix(self):
        proposed = [
            ("a", "/a.jsonl", "same-title-here"),
            ("b", "/b.jsonl", "same-title-here"),
        ]
        with patch.object(sn, "generate_title", return_value="same-title-here"):
            result = sn._deduplicate_with_regen(proposed, {}, "haiku", set())
        titles = [t for _, _, t in result]
        assert titles[0] == "same-title-here"
        assert titles[1] == "same-title-here-2"


class TestBackfillCandidates:
    def test_excludes_custom_titled_sessions(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        write_jsonl(proj / "s.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "custom-title", "customTitle": "already-named"},
        ])
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            sn.backfill(all_projects=False)
        assert "No untitled sessions" in capsys.readouterr().out

    def test_includes_ai_titled_sessions(self, tmp_path, capsys):
        # Sessions with only ai-title (no custom-title) are untitled from our perspective.
        # backfill must name them so they get a unique custom-title.
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "ai-title", "aiTitle": "Analyze programming languages in subdirectories"},
        ])
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value="analyze-programming-subdirectories"):
                with patch("builtins.print"):
                    sn.backfill(all_projects=False)
        assert '"custom-title"' in f.read_text()

    def test_excludes_subagent_files(self, tmp_path):
        # Regression: rglob("*.jsonl") was picking up session/subagents/*.jsonl
        proj = tmp_path / "proj"
        proj.mkdir()
        make_session(proj / "main.jsonl")
        subagent_dir = proj / "main" / "subagents"
        subagent_dir.mkdir(parents=True)
        subagent_file = subagent_dir / "agent-xyz.jsonl"
        make_session(subagent_file, "subagent task", "subagent done")
        before = subagent_file.read_text()

        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value="main-session-title"):
                with patch("builtins.print"):
                    sn.backfill(all_projects=False)

        # Subagent file must not be modified
        assert subagent_file.read_text() == before
        # Main session must have been named
        assert "main-session-title" in (proj / "main.jsonl").read_text()

    def test_deduplicates_titles_across_sessions(self, tmp_path):
        # Verifies _deduplicate_with_regen is actually called from backfill:
        # when two sessions would get the same title, they must end up with distinct ones.
        proj = tmp_path / "proj"
        proj.mkdir()
        make_session(proj / "a.jsonl")
        make_session(proj / "b.jsonl")
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", side_effect=[
                "same-python-title-here",  # session a initial
                "same-python-title-here",  # session b initial (duplicate)
                "python-distinct-variant",  # retry for the duplicate
            ]):
                with patch("builtins.print"):
                    sn.backfill(all_projects=False)

        def extract_custom_title(path):
            for line in path.read_text().splitlines():
                try:
                    e = json.loads(line)
                    if e.get("type") == "custom-title":
                        return e["customTitle"]
                except Exception:
                    pass
            return None

        a_title = extract_custom_title(proj / "a.jsonl")
        b_title = extract_custom_title(proj / "b.jsonl")
        assert a_title is not None and b_title is not None
        assert a_title != b_title

    def test_includes_untitled_sessions(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "s.jsonl"
        make_session(f)
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value="generated-title-name"):
                sn.backfill(all_projects=False)
        assert "generated-title-name" in f.read_text()

    def test_no_projects_dir(self, tmp_path, capsys):
        with patch.object(sn.Path, "home", return_value=tmp_path):
            sn.backfill(all_projects=True)
        assert "No projects directory" in capsys.readouterr().out

    def test_no_project_dir_for_cwd(self, tmp_path, capsys):
        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)
        with patch.object(sn.Path, "home", return_value=tmp_path):
            with patch.object(sn, "_cwd_project_dir", return_value=tmp_path / "nonexistent"):
                sn.backfill(all_projects=False)
        assert "No session directory" in capsys.readouterr().out

    def test_all_projects(self, tmp_path, capsys):
        projects_dir = tmp_path / ".claude" / "projects"
        proj = projects_dir / "myproject"
        proj.mkdir(parents=True)
        f = proj / "s.jsonl"
        make_session(f)
        with patch.object(sn.Path, "home", return_value=tmp_path):
            with patch.object(sn, "generate_title", return_value="all-projects-title"):
                sn.backfill(all_projects=True)
        assert "all-projects-title" in f.read_text()

    def test_non_dir_entries_skipped_in_all_projects(self, tmp_path):
        projects_dir = tmp_path / ".claude" / "projects"
        proj = projects_dir / "myproject"
        proj.mkdir(parents=True)
        make_session(proj / "s.jsonl")
        (projects_dir / "stray-file.json").write_text("{}")
        with patch.object(sn.Path, "home", return_value=tmp_path):
            with patch.object(sn, "generate_title", return_value="skipped-nondir-title"):
                with patch("builtins.print"):
                    sn.backfill(all_projects=True)
        assert "skipped-nondir-title" in (proj / "s.jsonl").read_text()

    def test_no_proposals_when_all_generation_fails(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        make_session(proj / "s.jsonl")
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value=None):
                sn.backfill(all_projects=False)
        assert "No titles could be generated" in capsys.readouterr().out

    def test_dry_run_applies_on_confirm(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "s.jsonl"
        make_session(f)
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value="dry-run-applied-title"):
                with patch("builtins.input", return_value="y"):
                    sn.backfill(all_projects=False, dry_run=True)
        assert "dry-run-applied-title" in f.read_text()
        assert "Applied" in capsys.readouterr().out

    def test_dry_run_cancels_on_no(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "s.jsonl"
        make_session(f)
        original = f.read_text()
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value="dry-run-cancel-title"):
                with patch("builtins.input", return_value="n"):
                    sn.backfill(all_projects=False, dry_run=True)
        assert f.read_text() == original
        assert "Cancelled" in capsys.readouterr().out

    def test_dry_run_cancels_on_eof(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        make_session(proj / "s.jsonl")
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value="dry-run-eof-title"):
                with patch("builtins.input", side_effect=EOFError):
                    sn.backfill(all_projects=False, dry_run=True)
        assert "Cancelled" in capsys.readouterr().out


class TestBackfillKeyboardInterrupt:
    def test_keyboard_interrupt_during_generation(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        make_session(proj / "s.jsonl")
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "as_completed", side_effect=KeyboardInterrupt):
                sn.backfill(all_projects=False)
        assert "Cancelled" in capsys.readouterr().out
