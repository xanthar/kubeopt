#!/bin/bash
# Claude Harness - Track File Write (PostToolUse)
# Tracks files written for progress tracking
# Input: JSON via stdin with tool_input.file_path

# Read JSON from stdin
INPUT_JSON=$(cat)

# Extract file path
FILE_PATH=$(echo "$INPUT_JSON" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

# Skip if no file path or harness not initialized
[ -z "$FILE_PATH" ] && exit 0
[ -f ".claude-harness/config.json" ] || exit 0

# Skip harness internal files
case "$FILE_PATH" in
    */.claude-harness/*|*/.git/*|*.log|*.pyc|*/__pycache__/*|*/node_modules/*|*.env*)
        exit 0
        ;;
esac

# Track the file in progress
claude-harness progress file "$FILE_PATH" 2>/dev/null || true

# Also track in context (estimate tokens for content written)
CONTENT_LENGTH=$(echo "$INPUT_JSON" | jq -r '.tool_input.content // empty' 2>/dev/null | wc -c)
if [ "$CONTENT_LENGTH" -gt 0 ]; then
    claude-harness context track-file "$FILE_PATH" "$CONTENT_LENGTH" --write 2>/dev/null || true
fi

exit 0
