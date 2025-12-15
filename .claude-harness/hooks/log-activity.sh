#!/bin/bash
# Claude Harness - Activity Logger (PostToolUse)
# Logs bash commands for session tracking
# Input: JSON via stdin with tool_input.command

# Read JSON from stdin
INPUT_JSON=$(cat)

# Extract command
COMMAND=$(echo "$INPUT_JSON" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Skip if no command or harness not initialized
[ -z "$COMMAND" ] && exit 0
[ -f ".claude-harness/config.json" ] || exit 0

LOG_DIR=".claude-harness/session-history"
LOG_FILE="$LOG_DIR/activity-$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"
echo "[$(date -Iseconds)] Bash: ${COMMAND:0:200}" >> "$LOG_FILE"

# Track command execution in context
COMMAND_LEN=${#COMMAND}
claude-harness context track-command "$COMMAND_LEN" 2>/dev/null || true

exit 0
