# Humiley Portal — working agreement

## Work in your own git worktree

There are two reasons. The second one is worse.

**The shared checkout is inside OneDrive, and so is its `.git`.** The repo lives at
`~/Library/CloudStorage/OneDrive-Humiley(2)/Claude Projects/TimeKeeping Web App`, which means cloud
sync can rewrite git's own ref store underneath a running session. On 2026-09-04 it was found
holding `main` at a commit authored 2026-08-02 — **25 days behind that branch's own last reflog
entry**, with no reflog record of the move, `core.logAllRefUpdates = true`, and no loose
`.git/refs/heads/main` at all: the branch existed only inside a `packed-refs` written on a day
nobody ran git. A branch moved backwards and git never ran. That is not something git does; it is
what restoring an older copy of a synced file looks like.

`~/humiley-worktrees/` is **outside** the synced folder. That is the real reason to work there.

Second, and the older reason: several Claude Code sessions run against this checkout at the same
time, so in a shared working tree a blanket `git add` stages whatever every *other* session has in
flight. That has happened twice — most recently `27eca4d` swallowed a complete EN/VN i18n pass into
an unrelated tender commit and pushed it, and by the time anyone noticed there was nothing left to
separate without force-pushing a branch three other sessions were on.

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

- **Check that its `main` has not been moved backwards, before you trust anything else.** Two
  commands, and they cost nothing:

  ```bash
  git rev-list --count HEAD..origin/main            # how far behind origin/main you are
  LAST=$(git reflog show main --format=%H | head -1)
  [ "$(git rev-parse main)" != "$LAST" ] && git merge-base --is-ancestor main "$LAST" \
    && echo "REF MOVED BACKWARDS — stop"
  ```

  The first says how stale you are; the second says whether the branch sits *strictly behind its own
  reflog*, which no git command produces. **The `!=` is load-bearing** — a commit is an ancestor of
  itself, so `merge-base --is-ancestor main "$LAST"` alone fires on every healthy repository. Both
  branches of this were tested: on a healthy branch the guarded form is silent and the unguarded one
  fires; against a ref moved backwards by a non-git file write (the incident's own mechanism, since
  `update-ref` appends to an existing reflog and cannot reproduce it) the guarded form fires. If it
  prints, stop — do not commit, do not reset, and tell the user. In the state found on 2026-09-04 an ordinary `git commit -m` there would have
  carried **47,490 deletions** into `main`, because a 395-commit-old tree diffs against current main
  that way. Nothing had to be intended; the staged state was already loaded.
- **Never** run `git add -A` or `git add .` here. Stage explicit paths you know are yours.
- Files change **under you, mid-session**. `templates/index.html` once shifted 118 lines while a
  task was in progress. Re-read before patching, and apply edits by unique-string match, never by
  a line number you captured earlier.
- Before committing, classify every hunk — `git diff -U0 <file>` — and confirm each one is yours.
- Check `ListAgents` early so you know who else is live.
- **Preserve before you clean up.** A tree here can hold content that is in no commit anywhere —
  check with `git ls-files -s <file>` and hunt the blob through `git rev-list origin/main` before
  assuming a `git reset --hard` is recoverable. `git stash create` writes a dangling commit holding
  the exact state and modifies neither the index nor the working tree; it is the safe first move,
  and it is the user's call, not yours.

## Preview servers are shared too

`preview_start` caps at 5 dev servers per folder, and peer sessions hold them. A worktree gets its
own deterministic port (8100–8899, derived from the name), so it does not collide. If you must run
outside a worktree, do not add a config to the shared `.claude/launch.json` without removing it
afterwards.
