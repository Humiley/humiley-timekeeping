# Humiley Portal — working agreement

## Work in your own git worktree

Several Claude Code sessions run against this checkout at the same time. In a shared working tree a
blanket `git add` stages whatever every *other* session has in flight. That has happened twice:
most recently `27eca4d` swallowed a complete EN/VN i18n pass into an unrelated tender commit and
pushed it, and by the time anyone noticed there was nothing left to separate without force-pushing
a branch three other sessions were on.

**At the start of any session that will edit files:**

```bash
tools/worktree.sh new <short-name>
```

Then call `EnterWorktree` with the path it prints. Work, commit and push from there. `git add -A`
in a worktree can only ever stage your own changes, and the preview server it configures serves the
worktree directly — so an edit to `templates/index.html` is live on the next request with no copy
or sync step.

`tools/worktree.sh list` shows every worktree; `tools/worktree.sh rm <name>` removes one and
refuses to drop a branch holding commits that are not on `origin/main`.

## If you are working in the shared checkout anyway

- **Never** run `git add -A` or `git add .` here. Stage explicit paths you know are yours.
- Files change **under you, mid-session**. `templates/index.html` once shifted 118 lines while a
  task was in progress. Re-read before patching, and apply edits by unique-string match, never by
  a line number you captured earlier.
- Before committing, classify every hunk — `git diff -U0 <file>` — and confirm each one is yours.
- Check `ListAgents` early so you know who else is live.

## Preview servers are shared too

`preview_start` caps at 5 dev servers per folder, and peer sessions hold them. A worktree gets its
own deterministic port (8100–8899, derived from the name), so it does not collide. If you must run
outside a worktree, do not add a config to the shared `.claude/launch.json` without removing it
afterwards.
