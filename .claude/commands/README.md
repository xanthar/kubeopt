# Claude Harness Commands

These slash commands integrate claude-harness with Claude Code.

## Available Commands

| Command | Description |
|---------|-------------|
| `/harness-context` | Show context/token usage |
| `/harness-context-compress` | Compress session (handoff + archive + reset) |
| `/harness-context-handoff` | Generate a handoff document for session continuity |
| `/harness-context-summary` | Generate a context summary |
| `/harness-delegation-add-rule` | Add a custom delegation rule |
| `/harness-delegation-auto` | Toggle auto-delegation hints |
| `/harness-delegation-disable` | Disable subagent delegation |
| `/harness-delegation-enable` | Enable subagent delegation |
| `/harness-delegation-rules` | Show delegation rules |
| `/harness-delegation-status` | Show delegation status and metrics |
| `/harness-delegation-suggest` | Get delegation suggestions for a feature |
| `/harness-detect` | Detect project stack without initializing |
| `/harness-e2e-generate` | Generate E2E test for a feature |
| `/harness-feature-add` | Add a new feature with subtasks |
| `/harness-feature-block` | Block a feature with a reason |
| `/harness-feature-complete` | Mark a feature as complete |
| `/harness-feature-done` | Mark a subtask as done |
| `/harness-feature-info` | Show detailed feature information |
| `/harness-feature-list` | List all features |
| `/harness-feature-note` | Add a note to a feature |
| `/harness-feature-start` | Start working on a feature |
| `/harness-feature-tests` | Mark feature tests as passing/failing |
| `/harness-feature-unblock` | Unblock a blocked feature |
| `/harness-help` | Show all available harness commands |
| `/harness-init` | Initialize claude-harness in the current project |
| `/harness-optimize` | Show context optimization status |
| `/harness-optimize-cache` | Show exploration cache status |
| `/harness-optimize-cache-clear` | Clear exploration cache |
| `/harness-optimize-filter` | Show which files would be tracked/skipped |
| `/harness-optimize-prune` | Prune stale context references |
| `/harness-optimize-summary` | Show compact context summary |
| `/harness-orchestrate` | Evaluate and suggest automatic task delegation |
| `/harness-orchestrate-queue` | Generate delegation queue for current feature |
| `/harness-orchestrate-status` | Show orchestration status and metrics |
| `/harness-progress` | Show current session progress |
| `/harness-progress-blocker` | Add a blocker to progress |
| `/harness-progress-completed` | Add a completed item to progress |
| `/harness-progress-file` | Track a modified file |
| `/harness-progress-history` | View session history |
| `/harness-progress-new-session` | Start a new session (archives current) |
| `/harness-progress-wip` | Add a work-in-progress item |
| `/harness-run` | Run the project's init script |
| `/harness-status` | Show current harness status (context, features, progress) |

## Usage

Type any command in Claude Code, e.g.:
- `/harness-status` - Show current status
- `/harness-feature-add` - Add a new feature
- `/harness-delegation-suggest` - Get delegation suggestions

Commands that accept arguments can be used like:
- `/harness-feature-start F-001`
- `/harness-feature-note F-001 "This is a note"`

## First Time Setup

If claude-harness is not initialized yet, run:
- `/harness-init` - Interactive initialization within Claude Code

Or run directly in terminal:
```bash
claude-harness init
```
