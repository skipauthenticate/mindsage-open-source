# Claude Code Token Optimization Guide

Quick reference for reducing Claude Code token usage by 30-60%.

## Quick Wins (Do These First)

### 1. Use `!` for Direct Commands
Run bash commands without model processing - costs zero tokens:
```
! git status
! npm test
! cat package.json
! grep -r "TODO" ./src
```

Chain commands:
```
! git status && git log --oneline -5
```

### 2. Clear Context Between Tasks
```
/clear          # Start fresh when switching tasks
/rename         # Name session before clearing for easy resume
/resume         # Return to previous session later
```

### 3. Check Token Usage
```
/cost           # See current session cost
/context        # See what's consuming context space
```

### 4. Use Compact with Instructions
When context gets large:
```
/compact Focus on code changes and API patterns
```

## Model Selection

| Task Type | Model | Command |
|-----------|-------|---------|
| Simple fixes, file edits | Haiku | `/model haiku` |
| Most coding tasks | Sonnet | `/model sonnet` |
| Complex architecture | Opus | `/model opus` |

Switch mid-session: `/model sonnet`

## Write Specific Prompts

**Bad (triggers broad scanning):**
> "Improve this codebase"
> "Fix the bug"

**Good (minimal file reads):**
> "Add input validation to the login function in src/auth.ts"
> "Fix the null check on line 42 of ChatPanel.tsx"

## Use Plan Mode for Complex Tasks

Press `Shift+Tab` before implementation to:
- Explore codebase first
- Get approval before writing code
- Prevent expensive re-work

## Reduce MCP Server Overhead

Check active servers: `/mcp`

Prefer CLI tools over MCP servers when available:
- `gh` instead of GitHub MCP
- `aws` instead of AWS MCP
- `gcloud` instead of GCP MCP

## Extended Thinking

Disable for simple tasks in `/config` or set lower budget:
```
MAX_THINKING_TOKENS=8000
```

## Session Hooks (Automatic Context)

Hooks in `.claude/hooks/` use **relative paths** - work on any environment (Mac, Jetson, Docker):
- `filter-test-output.sh` - Auto-filters test output to failures only
- `filter-build-output.sh` - Auto-filters build output to errors only
- `session-start.sh` - Shows git, services, detects Jetson/Docker

Run manually:
```
! .claude/hooks/session-start.sh
```

## Workflow Best Practices

1. **Batch `!` commands first** - Load context, then ask questions
2. **Course-correct early** - Press `Escape` if going wrong direction
3. **Use `/rewind`** - Double-tap Escape to restore previous state
4. **Test incrementally** - Write one file, test, continue
5. **Give verification targets** - Include test cases in prompts

## MindSage-Specific Tips

### Quick Commands
```
! .claude/hooks/session-start.sh        # Show environment + services
! .claude/scripts/check-resources.sh    # Check memory/GPU (Jetson/Docker)
```

### Backend Development
```
! cd mindsage && npm run dev        # Start backend
! curl localhost:3003/api/stats     # Check API
```

### Frontend Development
```
! cd mindsage-frontend && npm run dev   # Start frontend
! npm run lint                          # Check for errors
```

### Vector Store
```
! curl localhost:8085/health            # Check vector store
```

## Jetson Orin Nano Tips

The device has ~7.4GB shared CPU/GPU memory. Key constraints:

- **One large model at a time** - TinyLlama OR Reranker, not both
- **Check memory before indexing**: `! .claude/scripts/check-resources.sh`
- **Monitor with tegrastats**: `! timeout 5 tegrastats`

## Docker Tips

When running in Docker:
```
! docker stats --no-stream              # Check container memory
! docker logs mindsage-backend --tail 50  # Recent logs (filtered)
```

## Cost Reference

| Activity | Typical Cost |
|----------|--------------|
| Average daily usage | $6/day |
| 90th percentile | $12/day |
| Monthly (Sonnet) | $100-200 |

## Sources

- [Claude Code Costs Documentation](https://code.claude.com/docs/en/costs)
- [DEV Community - ! Prefix Guide](https://dev.to/rajeshroyal/stop-wasting-tokens-the-prefix-that-every-claude-code-user-needs-to-know-2c6i)
- [Geeky Gadgets - Optimization Techniques](https://www.geeky-gadgets.com/claude-code-optimization-techniques/)
