#!/bin/bash
# Claude Harness - Track File Read (PostToolUse)
# Tracks files read for context estimation
# Input: JSON via stdin with tool_input.file_path

# Read JSON from stdin
INPUT_JSON=$(cat)

# Extract file path
FILE_PATH=$(echo "$INPUT_JSON" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

# Skip if no file path or harness not initialized
[ -z "$FILE_PATH" ] && exit 0
[ -f ".claude-harness/config.json" ] || exit 0

# Get file size for token estimation
if [ -f "$FILE_PATH" ]; then
    CHAR_COUNT=$(wc -c < "$FILE_PATH" 2>/dev/null || echo 1000)
    claude-harness context track-file "$FILE_PATH" "$CHAR_COUNT" 2>/dev/null || true
fi

exit 0
