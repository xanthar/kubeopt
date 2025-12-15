#!/bin/bash
# Claude Harness - Subtask Audit Hook
# Checks for in-progress features with incomplete subtasks at session end

[ -f ".claude-harness/features.json" ] || exit 0

# Use Python for JSON parsing (more reliable than jq/bash)
python3 << 'PYTHON_SCRIPT'
import json
import sys

try:
    with open(".claude-harness/features.json") as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    sys.exit(0)

# Find in-progress features
features = data.get("features", [])
in_progress = [f for f in features if f.get("status") == "in_progress"]

if not in_progress:
    sys.exit(0)

# Check each in-progress feature for incomplete subtasks
for feature in in_progress:
    fid = feature.get("id", "?")
    name = feature.get("name", "Unknown")
    subtasks = feature.get("subtasks", [])

    if not subtasks:
        continue

    incomplete = [st for st in subtasks if not st.get("completed", False)]
    completed = [st for st in subtasks if st.get("completed", False)]

    if incomplete:
        print("")
        print("=" * 60)
        print(f"⚠️  SUBTASK REMINDER: {fid} - {name}")
        print("=" * 60)
        print(f"Completed: {len(completed)}/{len(subtasks)} subtasks")
        print("")
        print("Incomplete subtasks:")
        for st in incomplete:
            st_name = st.get("name", "Unknown")
            print(f"  ○ {st_name}")
        print("")
        print("If work was done on these, mark them complete:")
        for st in incomplete:
            st_name = st.get("name", "Unknown")
            # Truncate long names for command suggestion
            short_name = st_name[:30] + "..." if len(st_name) > 30 else st_name
            print(f"  claude-harness feature done {fid} \"{short_name}\"")
        print("=" * 60)
PYTHON_SCRIPT

exit 0
