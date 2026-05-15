# claude-session-naming

Automatic session naming for Claude Code. Install it as a `SessionEnd` hook and sessions
are named automatically when they end. Run with `backfill` to name existing untitled
sessions. Titles are short kebab-case slugs (e.g. `fix-webhook-retry-fail`) generated
by `claude -p`.

Inspired by [claude-rename](https://github.com/sathwick-p/claude-rename). Python port with no external dependencies. Unlike claude-rename, this runs once at session exit rather than in the background after each exchange.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Claude Code CLI (`claude`) installed and authenticated

## Commands

| Command | Description |
| --------- | ------------- |
| `claude-session-namer install` | Install the SessionEnd hook |
| `claude-session-namer uninstall` | Remove the SessionEnd hook |
| `claude-session-namer status` | Show installation status |
| `claude-session-namer backfill [--all] [--dry-run] [--model <model>] [--concurrency <n>]` | Name untitled sessions in the current project (`--all` for every project, `--dry-run` to preview and confirm, `--concurrency` to set parallel workers for large backlogs (default: 5), `--model` to override the default haiku) |

After installing, run `/hooks` in Claude Code or restart to pick up the new hook.

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
   first few turns of the conversation as context — naming runs async and typically
   completes 10–20 seconds after the session ends
4. Appends `{"type": "custom-title", "customTitle": "fix-stripe-webhook-retry", ...}`
   to the session JSONL
