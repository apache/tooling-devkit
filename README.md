# Tooling devkit

The developer files that every Apache Tooling repository shares: the agent rules, the Bash guard, the
commands, the scripts and the CI workflows. One source, so that a fix made in one repository reaches the
others instead of drifting. The decision is D-18 in
[apache/tooling-migration](https://github.com/apache/tooling-migration); the work is tracked in
[tooling-migration#50](https://github.com/apache/tooling-migration/issues/50).

## What is here

The files sit at the paths a service repository uses for them.

| Path | What it is |
| ---- | ---------- |
| `AGENTS.shared.md` | the rules every repository shares; a repository's own `AGENTS.md` reads it first |
| `.claude/hooks/guard-bash.sh`, `.claude/hooks/guard-bash.test.sh` | the guard that holds the rules in `AGENTS.shared.md`, and its tests |
| `.claude/commands/` | the pre-PR adversarial pass, the end-to-end run and the screenshots |
| `.claude/settings.json` | the permission allowlist and the hook registration |
| `scripts/` | the container wrappers, the worktree scripts, the review reader and the CI helpers |
| `.github/` | the shared workflows and the apt-install action |
| `devkit.conf` | the names the shared files read: `DEVKIT_SERVICE`, `DEVKIT_REPOSITORY` |

A service repository has a `devkit.conf` of its own. The shared files contain no name of any one service:
the variables they read start with `DEVKIT_`, and the image, volume and container names take the service
name from `devkit.conf`.

## Status

This is the first version. It holds the files as tooling-agenda has them, with the names taken out. Not
yet here: the sync script, `devkit.lock`, the drift check, the extension points for what a repository
needs in its own form, and `pr-preflight.sh`. See the tracking issue.

## Tests

The shell tests need `sh`, `git`, `flock` and the usual Unix tools:

```sh
for t in .claude/hooks/guard-bash.test.sh scripts/*.test.sh scripts/ci/*.test.sh; do sh "$t" || echo "FAILED: $t"; done
```

## License

Apache License 2.0. See `LICENSE`.
