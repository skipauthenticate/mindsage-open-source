#!/bin/bash
# PreToolUse hook - filters verbose test output to save tokens
# Only shows failures and errors instead of full test output

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command' 2>/dev/null)

# Check if command is a test runner
if [[ "$cmd" =~ ^(npm\ test|npm\ run\ test|npx\ jest|npx\ vitest|pytest|go\ test) ]]; then
    # Filter to show only failures and limit output
    filtered_cmd="$cmd 2>&1 | grep -A 10 -E '(FAIL|ERROR|error:|failed|Error:)' | head -100"
    echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"allow\",\"updatedInput\":{\"command\":\"$filtered_cmd\"}}}"
else
    # Pass through non-test commands unchanged
    echo "{}"
fi
