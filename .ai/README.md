# .ai/ Directory

This directory contains AI-readable project context for automated development agents
(Devin, Claude Code, Gemini, Cursor, etc.).

## Files

| File | Purpose | When to read |
|------|---------|-------------|
| `CONTEXT.md` | Project overview, architecture, import graph, data models, API, env vars | Always (start here) |
| `STATUS.md` | Current phase, completed work, prioritized TODOs with rationale | Always |
| `TIPS.md` | Accumulated tips with searchable tags (living document) | Before making changes |
| `PLAYBOOK.md` | Task workflows, anti-patterns, code quality checklist, agent-specific notes | Before starting a task |
| `README.md` | This file | If you're unsure where to start |

## For AI Agents

**Start here:**
1. Read `CONTEXT.md` for the full project picture and import dependency graph
2. Read `STATUS.md` to know what's done, what's next, and why
3. Read `TIPS.md` for gotchas and known behaviors (filter by tags)
4. Follow `PLAYBOOK.md` for task-specific guidance and anti-patterns

**After completing work:**
1. Update `STATUS.md` with your progress (include **Why** for new TODOs)
2. Append discoveries to `TIPS.md` with appropriate **Tags**
