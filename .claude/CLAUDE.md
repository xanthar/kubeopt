# KubeOpt AI

AI-Driven Kubernetes Resource & Cost Optimizer

---

## Quick Reference

| Item | Value |
|------|-------|
| Port | 5000 |
| Health | `GET /api/v1/health` |
| API Docs | `GET /api/docs` (Swagger UI) |
| Start | `python run.py` |
| Test | `pytest tests/unit/ -v` |
| Coverage | 80% minimum |

---

# CLAUDE HARNESS INTEGRATION

> **Note for public contributors:** Claude Harness is an optional workflow system for AI-assisted development. You can use this project without it - the harness commands below are for developers who have claude-harness installed.

## WHAT IS THIS?

Claude Harness is a **persistent workflow system** that tracks your work across sessions. Unlike Claude's internal TodoWrite (which resets each session), harness data persists in files:

- `features.json` - Features and subtasks (survives session restarts)
- `progress.md` - Session handoff notes (readable by next session)
- `discoveries.json` - Findings and decisions (institutional memory)

**Why use harness commands instead of TodoWrite?**
→ Your progress is SAVED and visible to the next session
→ Subtask completion is TRACKED for interrupted sessions
→ The user can see your progress in real-time via `feature list`

## MANDATORY BEHAVIORS

⚠️ **CRITICAL:** Do NOT use Claude's internal TodoWrite for feature/subtask tracking - use HARNESS commands only!

**Session Start:**
1. `./scripts/init.sh` → read `progress.md` → `feature list`
2. If pending features exist: `feature start <ID>`
3. If NO pending features: `feature add "<name>" -s "subtask1" -s "subtask2"` then `feature start <ID>`

**During Work (after completing each subtask):**
→ Run: `feature done <ID> "<subtask name>"` immediately after finishing each subtask
→ Do NOT batch subtask completions - mark each one as you finish it

**Session End:** Update `progress.md` → verify all subtasks marked → `feature complete <ID>` → commit

**Rules:**
- ONE feature at a time: `feature start` before work → complete subtasks one at a time with `feature done` → `feature complete` after tests pass
- ALWAYS use `feature add` to create new features before starting work on them
- NEVER edit `features.json` manually - use CLI commands only
- ALL subtasks must be marked done with `feature done` before `feature complete`

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

**When to delegate (preserves your context):**
→ Writing tests: Delegate to `test` subagent after implementing code
→ Exploring codebase: Delegate to `explore` subagent for file discovery
→ Documentation: Delegate to `document` subagent for READMEs
→ Code review: Delegate to `review` subagent for security/performance

**Keep in main agent:** Core implementation, user interaction, git commits

**Workflow:**
1. After implementing code: `delegation suggest <ID>` to see what to delegate
2. Use Task tool with appropriate subagent_type
3. Summarize results (<500 words) back to main context

## ORCHESTRATION

Auto-workflow enabled. Commands:
- `orchestrate run <FEATURE_ID>` - Execute workflow
- `orchestrate plan <FEATURE_ID>` - Preview steps
- `orchestrate status` - Current state

## DISCOVERIES

**Record important findings for future sessions:**
→ Architectural decisions: `discovery add "Chose X over Y because..." -t architecture`
→ Gotchas/bugs found: `discovery add "Watch out for X when..." -t gotcha`
→ Dependencies: `discovery add "Requires X to be configured..." -t dependency`
→ Performance notes: `discovery add "This is slow because..." -t performance`

**When to add discoveries:**
- Found unexpected behavior or edge case
- Made a design decision with tradeoffs
- Discovered something future sessions should know

Commands: `discovery list`, `discovery search "<query>"`

## DOCUMENTATION UPDATES

**After each `feature complete <ID>`, update documentation:**

1. **CHANGELOG.md** - Add entry under `## [Unreleased]`:
   ```
   ### Added/Changed/Fixed
   - Brief description of what changed
   ```

2. **ROADMAP.md** - Mark completed features, update priorities

3. **README.md** - Update if user-facing behavior changed

**Keep entries concise.** One line per change, grouped by type.

## CONTEXT TRACKING

Monitor token usage and generate handoffs:
- `context show` - Current usage stats
- `context summary` - Generate session summary
- `context handoff` - Create handoff document

---

## Project-Specific Rules

### API Conventions
- All endpoints under `/api/v1/`
- JSON request/response with `Content-Type: application/json`
- Error responses: `{"error": "message", "code": "ERROR_CODE", "details": {}}`
- Pagination: `?page=1&per_page=50` (max 100)

### Code Organization
- **Models:** `kubeopt_ai/core/models.py` - SQLAlchemy models
- **Schemas:** `kubeopt_ai/core/schemas.py` - Pydantic validation
- **Routes:** `kubeopt_ai/routes/` - Flask blueprints
- **Services:** `kubeopt_ai/core/` - Business logic
- **LLM:** `kubeopt_ai/llm/` - Claude AI integration

### Environment Variables (Required)
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/kubeopt
LLM_API_KEY=sk-ant-...           # Anthropic API key
PROMETHEUS_BASE_URL=http://prometheus:9090
SECRET_KEY=your-secret-key       # Flask secret
JWT_SECRET_KEY=your-jwt-secret   # JWT signing key
```

### Testing Requirements
- All new features require unit tests
- Mock external services (Prometheus, Claude API, K8s)
- Target 80% coverage on new code
- Run tests: `pytest tests/unit/ -v --cov=kubeopt_ai`

### Database Migrations
```bash
# Create migration after model changes
alembic revision -m "describe change" --autogenerate

# Apply migrations
alembic upgrade head
```

### Security Guidelines
- Never commit secrets or API keys
- Use environment variables for all configuration
- Validate all user input with Pydantic schemas
- Rate limiting enabled by default (100/hour)

---

**Version:** 1.0.0
**License:** MIT
