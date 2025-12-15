# kubeopt

KubeOpt AI – AI-Driven Kubernetes Resource & Cost Optimizer


# CLAUDE HARNESS INTEGRATION

## MANDATORY BEHAVIORS

**Session Start:**
1. `./scripts/init.sh` → read `progress.md` → `feature list`
2. If pending features exist: `feature start <ID>`
3. If NO pending features: `feature add "<name>" -s "subtask1" -s "subtask2"` then `feature start <ID>`

**Session End:** Update `progress.md` → `feature done <ID> <subtask>` → commit

**Rules:**
- ONE feature at a time (start before work, complete after tests pass)
- NEVER edit `features.json` manually - use CLI commands only
- ALL subtasks must complete before feature completion
- ALWAYS add new features via CLI before starting work on them

## COMMANDS

| Action | Command |
|--------|---------|
| List features | `feature list` |
| Start feature | `feature start <ID>` |
| Complete subtask | `feature done <ID> <subtask>` |
| Mark tests pass | `feature tests <ID>` |
| Complete feature | `feature complete <ID>` |
| Add feature | `feature add "<name>" [-p priority] [-s subtask]` |
| Sync progress | `feature sync [--dry-run]` |
| Add completed | `progress completed "<desc>"` |
| Add WIP | `progress wip "<desc>"` |

All commands: `claude-harness <command>`

## GIT RULES

- **Protected branches:** main, master
- **Branch prefixes:** feat/, fix/, chore/, docs/, refactor/
- **Blocked actions:** commit_to_protected_branch, push_to_protected_branch_without_confirmation, delete_backup_branches
- Verify branch before commits: `git branch --show-current`

## CONFIG

- Port: 5000 | Health: /api/v1/health
- Start: `python run.py`
- Test: `pytest tests/unit/ -v` (coverage: 80%)

## DELEGATION

Delegate to preserve context. Use Task tool for:
- `explore`: File discovery, codebase analysis
- `test`: Unit/E2E tests
- `document`: READMEs, docs
- `review`: Security, performance audits

Keep in main: Core implementation, user interaction, commits.

Workflow: `delegation suggest <ID>` → Task tool → summarize (<500 words)

## ORCHESTRATION

Auto-workflow enabled. Commands:
- `orchestrate run <FEATURE_ID>` - Execute workflow
- `orchestrate plan <FEATURE_ID>` - Preview steps
- `orchestrate status` - Current state

## DISCOVERIES

Track findings and requirements. Commands:
- `discovery add "<summary>" [-t tag]` - Record finding
- `discovery list [--tag TAG]` - List all
- `discovery search "<query>"` - Search

## CONTEXT TRACKING

Monitor token usage and generate handoffs:
- `context show` - Current usage stats
- `context summary` - Generate session summary
- `context handoff` - Create handoff document

---

## Project-Specific Rules

(Add your project-specific rules here)

---
**Version:** 1.0
**Maintained by:** Claude Harness
