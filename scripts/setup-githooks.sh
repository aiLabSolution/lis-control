#!/bin/sh
# Enable this repo's tracked git hooks. Run once per clone — the setting lives in
# .git/config and is shared by all of the clone's worktrees.
#
#   scripts/setup-githooks.sh
#
# Currently enables .githooks/pre-push, which rejects direct pushes to main/master
# so changes land via slice branch -> PR -> main. It is a client-side git hook, not
# a Claude Code PreToolUse gate: a blocked push just fails and the caller re-routes
# to a PR — no agent-loop interruption.
set -e

top=$(git rev-parse --show-toplevel)
cd "$top"

git config core.hooksPath .githooks
chmod +x .githooks/pre-push 2>/dev/null || true

echo "core.hooksPath -> .githooks (active for this clone and all its worktrees)."
echo "pre-push guard: direct pushes to main/master are now rejected locally."
