# claude-session-naming

Automatic session naming for Claude Code. Runs as a `SessionEnd` hook — when a session
ends it checks whether it has real content and no title yet, then spawns a background
worker that calls `claude -p` to generate a descriptive kebab-case title.

Inspired by [claude-rename](https://github.com/sathwick-p/claude-rename). Python port with no external dependencies. Unlike claude-rename, this runs once at session exit rather than in the background after each exchange.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Claude Code CLI (`claude`) installed and authenticated

## Commands

| Command | Description |
|---------|-------------|
| `claude-session-namer install` | Install the Stop hook |
| `claude-session-namer uninstall` | Remove the Stop hook |
| `claude-session-namer status` | Show installation status |
| `claude-session-namer backfill [--all] [--dry-run] [--model <model>] [--concurrency <n>]` | Name untitled sessions in the current project (`--all` for every project, `--dry-run` to preview and confirm, `--concurrency` to set parallel workers for large backlogs (default: 5), `--model` to override the default haiku) |

After installing, open `/hooks` in Claude Code (or restart) to pick up the new hook.

## Examples

```bash
claude-session-namer install
claude-session-namer backfill
claude-session-namer backfill --all --dry-run
claude-session-namer backfill --model sonnet
```

Override the default model globally with the `CLAUDE_SESSION_NAMER_MODEL` environment variable.

## How it works

1. `SessionEnd` hook fires once when the session exits
2. Skips if the session already has a custom title or lacks substantive content
   (at least one real user message + one assistant reply)
3. Spawns a detached background process that calls `claude -p --model haiku` with the
   first few turns of the conversation
4. Appends `{"type": "custom-title", "customTitle": "fix-stripe-webhook-retry", ...}`
   to the session JSONL
