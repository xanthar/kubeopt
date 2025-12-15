#!/bin/bash
# Claude Harness - Session Stop Hook
# Shows summary, saves handoff, and marks session closed when Claude stops

[ -f ".claude-harness/config.json" ] || exit 0

echo ""
echo "=== Session Summary ==="
claude-harness context show 2>/dev/null || true
echo "---"
claude-harness progress show 2>/dev/null || true
echo "======================="

# Check if auto_save_handoff is enabled (default: true)
AUTO_HANDOFF=$(cat .claude-harness/config.json 2>/dev/null | grep -o '"auto_save_handoff"[[:space:]]*:[[:space:]]*false' || echo "")
if [ -z "$AUTO_HANDOFF" ]; then
    # Auto-save handoff document
    echo ""
    echo "Saving session handoff..."
    claude-harness context handoff --save 2>/dev/null || true
fi

# Mark session as closed for clean restart
claude-harness context session-close 2>/dev/null || true

exit 0
