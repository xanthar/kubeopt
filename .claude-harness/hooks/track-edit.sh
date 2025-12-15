#!/bin/bash
# Claude Harness - Track File Edit (PostToolUse)
# Tracks files edited for progress tracking
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

# Estimate tokens for edit (old_string + new_string)
OLD_LEN=$(echo "$INPUT_JSON" | jq -r '.tool_input.old_string // empty' 2>/dev/null | wc -c)
NEW_LEN=$(echo "$INPUT_JSON" | jq -r '.tool_input.new_string // empty' 2>/dev/null | wc -c)
TOTAL_LEN=$((OLD_LEN + NEW_LEN))
if [ "$TOTAL_LEN" -gt 0 ]; then
    claude-harness context track-file "$FILE_PATH" "$TOTAL_LEN" --write 2>/dev/null || true
fi

exit 0
