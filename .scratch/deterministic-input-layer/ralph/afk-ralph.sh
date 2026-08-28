#!/bin/bash
# ==============================================================================
# afk-ralph.sh - Unattended loop Ralph runner with completion sigil
# Source: AI Hero (Matt Pocock) / https://www.aihero.dev/getting-started-with-ralph
# ==============================================================================
set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <iterations>"
  exit 1
fi

for ((i = 1; i <= $1; i++)); do
  echo "--- Ralph Iteration $i of $1 ---"
  
  # Run Claude Code in non-interactive print mode (-p)
  result=$(claude --permission-mode acceptEdits -p "@PRD.md @progress.txt \
1. Find the highest-priority incomplete task and implement it. \
2. Run your tests and type checks. \
3. Update the PRD with what was done. \
4. Append your progress to progress.txt. \
5. Commit your changes. \
ONLY WORK ON A SINGLE TASK. \
If the PRD is complete, output <promise>COMPLETE</promise>.")

  echo "$result"

  # Check if Claude emitted the completion sigil
  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo "?? PRD complete after $i iterations."
    exit 0
  fi
done

echo "?? Reached maximum iteration cap ($1). Some tasks may remain."
