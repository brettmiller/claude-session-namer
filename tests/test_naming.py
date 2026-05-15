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

    def test_skips_session_with_ai_title(self, tmp_path):
        # Regression: sessions with ai-title were previously processed as untitled
        f = tmp_path / "s.jsonl"
        write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "ai-title", "aiTitle": "Analyze programming languages"},
        ])
        with patch.object(sn, "generate_title") as mock_gen:
            result = sn.name_session("abc", str(f))
        assert result is None
        mock_gen.assert_not_called()

    def test_names_untitled_session(self, tmp_path):
        f = tmp_path / "s.jsonl"
        make_session(f)
        with patch.object(sn, "generate_title", return_value="python-language-overview"):
            result = sn.name_session("abc123", str(f))
        assert result == "python-language-overview"
        content = f.read_text()
        assert '"custom-title"' in content
        assert "python-language-overview" in content

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

    def test_excludes_ai_titled_sessions(self, tmp_path, capsys):
        # Regression: ai-titled sessions were treated as untitled candidates
        proj = tmp_path / "proj"
        proj.mkdir()
        write_jsonl(proj / "s.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "Hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "World"}},
            {"type": "ai-title", "aiTitle": "Analyze programming languages in subdirectories"},
        ])
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title") as mock_gen:
                sn.backfill(all_projects=False)
        mock_gen.assert_not_called()

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

    def test_includes_untitled_sessions(self, tmp_path, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "s.jsonl"
        make_session(f)
        with patch.object(sn, "_cwd_project_dir", return_value=proj):
            with patch.object(sn, "generate_title", return_value="generated-title-name"):
                sn.backfill(all_projects=False)
        assert "generated-title-name" in f.read_text()
