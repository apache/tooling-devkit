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
| `scripts/` | the container wrappers, the worktree scripts, the review reader and the CI helpers, among them the fast local test stage (`scripts/ci/fast_stage.py`) |
| `tests/` | the Python tests of the scripts that have them: so far the fast stage's |
| `workflows/` | the shared workflows, to copy into `.github/workflows/` of a service. They are kept here, not in `.github/workflows/`, so that GitHub does not run them in the kit |
| `.github/actions/` | the apt-install action |
| `.github/workflows/test.yml` | the kit's own CI: the shell tests, and the Python compiles |
| `devkit.conf` | the names the shared files read: `DEVKIT_SERVICE`, `DEVKIT_REPOSITORY` |

A service repository has a `devkit.conf` of its own. The variables the shared files read start with
`DEVKIT_`, and the image, volume and container names take the service name from `devkit.conf`. Some files
still carry what belongs to tooling-agenda: see "Status".

## Status

This is the first version. It holds the files as tooling-agenda has them, with the service name and the
variable prefix taken out. Not yet here: the sync script, `devkit.lock`, the drift check, the extension
points for what a repository needs in its own form, and `pr-preflight.sh`. See the tracking issue.

What still belongs to tooling-agenda, and has to be made general or taken out:

- `.claude/settings.json`: `Read(./agenda.yaml)`, and the `make container-minutes-reading` entries.
- `scripts/ci/verify.py`: `MINUTES_CORPUS` and the `corpus` stage, and the frontend fixtures under
  `tests/data`.
- `workflows/`: the ASF runner labels, the `subversion` and LDAP packages, and the reference to
  `minutes-corpus.yml`.
- `scripts/Caddyfile`: the ASF OAuth proxy.
- `scripts/pr-review.sh`: a comment that points at `scripts/pr-preflight.sh`.
- The variables that no script of the kit reads: the tests and the e2e specs of a service read
  `DEVKIT_E2E_URL`, `DEVKIT_E2E_HOST`, `DEVKIT_BEHAVIOUR_OUT` and others, so a service renames its own at
  the same time as it takes the kit.

## Tests

The shell tests need `sh`, `git`, `flock` and the usual Unix tools:

```sh
for t in .claude/hooks/guard-bash.test.sh scripts/*.test.sh scripts/ci/*.test.sh; do sh "$t" || echo "FAILED: $t"; done
python3 -m pytest tests -q
```

`pytest` is the only Python package the tests need. Two tests read the `Makefile` of a service, and skip
where there is none, as in the kit.

## License

Apache License 2.0. See `LICENSE`.
