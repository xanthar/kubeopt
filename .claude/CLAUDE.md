# kubeopt

KubeOpt AI – AI-Driven Kubernetes Resource & Cost Optimizer


# CLAUDE HARNESS INTEGRATION

## SESSION START RITUAL (MANDATORY)

At the START of every session, BEFORE any other work:

1. **Run init script:** `./scripts/init.sh`
2. **Read progress:** `.claude-harness/progress.md`
3. **Check features:** `claude-harness feature list`
4. **Pick ONE feature** with status "pending" or continue "in_progress"
5. **Start the feature:** `claude-harness feature start <ID>` (THIS IS REQUIRED!)

## SESSION END RITUAL (MANDATORY)

Before ending a session or when context is getting full:

1. **Update progress.md** with:
   - What was completed
   - Current work in progress
   - Blockers or issues
   - Next steps for the next session
   - Files modified

2. **Update features.json** - Mark completed features, update subtasks

3. **Commit work** if appropriate

## ONE FEATURE AT A TIME

- ALWAYS work on exactly ONE feature from features.json
- Mark it as "in_progress" before starting
- Complete ALL subtasks before marking "completed"
- Run tests before marking as complete

## FEATURE TRACKING COMMANDS (USE THESE!)

**You MUST use these commands to track progress:**

### Starting Work on a Feature
```bash
claude-harness feature start <ID>    # Mark feature as in_progress
claude-harness feature list          # See available features
```

### Completing Subtasks
```bash
claude-harness feature done <ID> <subtask>   # Mark subtask complete (fuzzy match)
claude-harness feature done F001 "database"  # Example: completes subtask containing "database"
```

### Completing Features
```bash
claude-harness feature complete <ID>  # Mark feature complete (after all subtasks done)
claude-harness feature tests <ID>     # Mark tests as passing
```

### Syncing Progress from Files
```bash
claude-harness feature sync           # Auto-match modified files to subtasks
claude-harness feature sync --dry-run # Preview what would be synced
```

### Progress Updates
```bash
claude-harness progress completed "Task description"  # Add completed item
claude-harness progress wip "Current work"           # Add work in progress
```

**IMPORTANT:** Call `feature start` BEFORE working on a feature, and `feature done` AFTER completing each subtask. This ensures accurate progress tracking.

## GIT WORKFLOW

- **NEVER commit to:** main, master
- **Branch naming:** feat/, fix/, chore/, docs/, refactor/
- **ALWAYS verify branch:** `git branch --show-current`
- **Require confirmation** before merging to protected branches

## BLOCKED ACTIONS

The following are blocked by harness hooks:
- commit_to_protected_branch
- push_to_protected_branch_without_confirmation
- delete_backup_branches

## TESTING REQUIREMENTS

- Unit tests: `pytest tests/unit/ -v`
- Coverage threshold: 80%
- Features are NOT complete until tests pass

## PROJECT QUICK REFERENCE

- **Port:** 5000
- **Health endpoint:** /api/v1/health
- **Start command:** `python run.py`
- **Test framework:** pytest

---

## SUBAGENT DELEGATION

This project uses subagent delegation to preserve main agent context.

### When to Delegate (use Task tool)

**Delegate these tasks to specialized subagents:**
- **Exploration** (`explore` subagent): File discovery, codebase analysis, pattern finding
- **Testing** (`test` subagent): Unit tests, E2E tests, integration tests
- **Documentation** (`document` subagent): READMEs, API docs, code comments
- **Review** (`review` subagent): Security audits, performance analysis, code review

**Keep in main agent:**
- Core feature implementation requiring integration decisions
- User interaction and clarification
- Final validation and commits
- Complex multi-file changes

### Delegation Workflow

1. Check subtasks with: `claude-harness delegation suggest <FEATURE_ID>`
2. For delegatable tasks, use the Task tool with structured prompts
3. Summarize subagent results concisely (under 500 words)
4. Continue with main implementation

### Delegation Prompt Template

When using Task tool for delegation:

```
Feature: [feature_name] (ID: [feature_id])
Subtask: [subtask_name]

Context:
- Relevant files: [list key files]
- Current progress: [brief status]

Task: [detailed description]

Constraints:
- Keep summary under 500 words
- Report absolute file paths
- Include line numbers when relevant

Output: YAML summary with: accomplishments, files, decisions, issues, next_steps
```

### Estimated Context Savings

| Task Type | Without Delegation | With Delegation | Savings |
|-----------|-------------------|-----------------|---------|
| Exploration | ~30K tokens | ~3-5K | 83-90% |
| Test Writing | ~20K tokens | ~5-8K | 60-75% |
| Documentation | ~15K tokens | ~3-5K | 67-80% |
| Code Review | ~25K tokens | ~5-10K | 60-80% |

---

## Project-Specific Rules

(Add your project-specific rules here)

---
**Version:** 1.0
**Maintained by:** Claude Harness
