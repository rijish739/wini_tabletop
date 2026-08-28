#!/bin/bash
# ==============================================================================
# ralph-once.sh - Single iteration / Human-in-the-loop Ralph runner
# Source: AI Hero (Matt Pocock) / https://www.aihero.dev/getting-started-with-ralph
# ==============================================================================

claude --permission-mode acceptEdits "@PRD.md @progress.txt \
1. Read the PRD and progress file. \
2. Find the next incomplete task and implement it. \
3. Commit your changes. \
4. Update progress.txt with what you did. \
ONLY DO ONE TASK AT A TIME."
