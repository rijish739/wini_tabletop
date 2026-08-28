#!/bin/bash
# ==============================================================================
# ralph.sh - Issues-directory variant with git log context injection
# Source: AI Hero / Matt Pocock Ralph Video/Guide Variant
# ==============================================================================

issues=$(cat issues/*.md 2>/dev/null || echo "No issues found")
commits=$(git log -n 5 --format="%H%n%ad%n%B---" --date=short 2>/dev/null || echo "No commits found")
prompt=$(cat ralph/prompt.md 2>/dev/null || echo "Implement the next highest-priority issue.")

claude --permission-mode acceptEdits \
  "Previous commits: $commits Issues: $issues $prompt"
