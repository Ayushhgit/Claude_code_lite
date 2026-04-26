# REVI Product Roadmap

REVI should compete with serious coding agents by being reliable first, then fast,
then delightful. The product target is not "chat with tools"; it is an autonomous
engineering workbench that can understand a repository, make scoped changes,
prove them, and keep the human in control.

## North Star

1. Trustworthy execution: every edit is based on fresh file reads, every command
   is auditable, and verification reports mean what they say.
2. Deep codebase intelligence: maintain a cheap, current map of symbols,
   dependencies, tests, and risky integration points.
3. Strong planning loop: classify work, draft a concrete plan, execute in small
   verified steps, review the diff, and preserve useful memory.
4. Product-grade UX: clean terminal output, a useful dashboard, predictable slash
   commands, and plain failure messages with next actions.
5. Safe autonomy: destructive file and Git actions require explicit approval, and
   shell execution is constrained or sandboxed wherever possible.

## Build Phases

### Phase 1: Reliability Foundation

- Replace misleading verification with real Ruff linting plus syntax fallback.
- Remove shell execution from Git wrappers.
- Add targeted regression tests for tool dispatch, verification, and model routing.
- Normalize encoding so README, CLI, and dashboard text render cleanly on Windows.
- Make Git safe-directory failures actionable without mutating user config silently.

### Phase 2: Agent Loop Quality

- Make tool selection deterministic, inspectable, and covered by tests.
- Track files read and edited per turn, then reject edits to stale file snapshots.
- Add structured edit sessions: plan, changed files, commands run, checks passed.
- Add retry budgets per failure type instead of a single broad loop cap.
- Save concise task memory only when it helps future work.

### Phase 3: Code Intelligence

- Extend the semantic graph with imports, call sites, tests, and route handlers.
- Add blast-radius checks before refactors, not only after edits.
- Cache AST and graph data with robust invalidation.
- Add repository health scoring: tests, lint, type checks, dependency drift.

### Phase 4: Dashboard

- Move embedded HTML into static assets or templates.
- Show current task, plan steps, changed files, command log, and verification state.
- Add graph filtering, search, and clickable source locations.
- Add secure webhook setup docs and event logs.

### Phase 5: Distribution

- Add a real package entry point, versioning, and release notes.
- Add a default config file with schema validation.
- Add CI that runs compile, Ruff, unit tests, and packaging checks.
- Provide a first-run setup wizard for keys, workspace, provider, and sandbox.

## Product Rules

- A check that is skipped must say it is skipped.
- A check that only compiles code must not be called lint.
- Agent edits must be small enough to review.
- The dashboard must never be required to understand what happened.
- Dangerous operations must be boring, explicit, and reversible where possible.
