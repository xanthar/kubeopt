#!/bin/bash
# Claude Harness - Git Safety Hook (PreToolUse)
# Blocks dangerous git operations
# Input: JSON via stdin with tool_input.command

# Read JSON from stdin
INPUT_JSON=$(cat)

# Extract the command from tool_input
COMMAND=$(echo "$INPUT_JSON" | jq -r '.tool_input.command // empty' 2>/dev/null)

# If no command found, allow
[ -z "$COMMAND" ] && exit 0

PROTECTED_BRANCHES="main master"

# Check current branch
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")

# Block commits on protected branches
for branch in $PROTECTED_BRANCHES; do
    if [ "$CURRENT_BRANCH" = "$branch" ]; then
        if echo "$COMMAND" | grep -qE "^git commit"; then
            echo "BLOCKED: Cannot commit on protected branch '$branch'. Create a feature branch first." >&2
            exit 2
        fi
    fi
done

# Block force pushes to protected branches
for branch in $PROTECTED_BRANCHES; do
    if echo "$COMMAND" | grep -qE "git push.*(-f|--force).*($branch|origin/$branch)"; then
        echo "BLOCKED: Cannot force push to protected branch '$branch'." >&2
        exit 2
    fi
done

# Block destructive rebase on protected branches
for branch in $PROTECTED_BRANCHES; do
    if echo "$COMMAND" | grep -qE "git rebase.*(origin/)?$branch"; then
        if [ "$CURRENT_BRANCH" = "$branch" ]; then
            echo "BLOCKED: Cannot rebase on protected branch '$branch'." >&2
            exit 2
        fi
    fi
done

exit 0
