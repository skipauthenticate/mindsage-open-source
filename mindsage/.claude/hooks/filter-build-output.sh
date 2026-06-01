#!/bin/bash
# PreToolUse hook - filters verbose build output to save tokens
# Only shows errors and warnings instead of full build log

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command' 2>/dev/null)

# Check if command is a build command
if [[ "$cmd" =~ ^(npm\ run\ build|npx\ tsc|npx\ vite\ build) ]]; then
    # Filter to show only errors and warnings
    filtered_cmd="$cmd 2>&1 | grep -E '(error|warning|Error|Warning|failed|Failed)' | head -50"
    echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"allow\",\"updatedInput\":{\"command\":\"$filtered_cmd\"}}}"
else
    echo "{}"
fi
