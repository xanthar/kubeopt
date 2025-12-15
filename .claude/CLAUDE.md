# kubeopt

KubeOpt AI – AI-Driven Kubernetes Resource & Cost Optimizer


# CLAUDE HARNESS INTEGRATION

## SESSION START RITUAL (MANDATORY)

At the START of every session, BEFORE any other work:

1. **Run init script:** `./scripts/init.sh`
2. **Read progress:** `.claude-harness/progress.md`
3. **Check features:** `.claude-harness/features.json`
4. **Pick ONE feature** with status "pending" or continue "in_progress"
5. **Update feature status** to "in_progress" before starting work

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
- E2E validation required if e2e_enabled is true

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
- E2E tests: `pytest e2e/ -v`
- Coverage threshold: 80%
- Features are NOT complete until tests pass

## PROJECT QUICK REFERENCE

- **Port:** 5000
- **Health endpoint:** /api/v1/health
- **Start command:** `python run.py`
- **Test framework:** pytest

---


## Project-Specific Rules

(Add your project-specific rules here)

---
**Version:** 1.0
**Maintained by:** Claude Harness
