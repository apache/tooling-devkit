# Tooling devkit

The developer files that every Apache Tooling repository shares: the agent rules, the Bash guard, the
commands and the scripts. One source, so that a fix made in one repository reaches the
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
| `.github/actions/` | the apt-install action |
| `.github/workflows/test.yml` | the kit's own CI: the shell tests, and the Python compiles |
| `devkit.conf` | the names the shared files read: `DEVKIT_SERVICE`, `DEVKIT_REPOSITORY` |
| `devkit.files` | the files a service may take, with where each goes; the rest is the kit's own |
| `scripts/devkit-sync.sh` | copies those files at a commit, and checks that a copy is still as the kit has it |

A service repository has a `devkit.conf` of its own. The variables the shared files read start with
`DEVKIT_`, and the image, volume and container names take the service name from `devkit.conf`. Some files
still carry what belongs to tooling-agenda: see "Status".

## Taking the kit

A service repository keeps its own `devkit.conf` and `devkit.lock`. The first copy of
`scripts/devkit-sync.sh` is made by hand; after that:

```sh
scripts/devkit-sync.sh <ref>      # a branch, a tag or a full commit id of the kit: copy the files, write the commit to devkit.lock
scripts/devkit-sync.sh --check                          # compare them with the kit at that commit
```

Nothing is committed for you. A repository that keeps a file as its own names it in `DEVKIT_SKIP` in
`devkit.conf`, paths separated by spaces. A copy that differs on purpose, for a time, goes in
`devkit.lock` with its issue and the day it ends:

```text
commit 0123456789abcdef0123456789abcdef01234567
override scripts/e2e-container.sh tooling-agenda#1142 until 2026-12-31
```

The sync leaves an overridden file as it is, and the check prints each override and fails after its day.
`DEVKIT_SOURCE` names another place to fetch the kit from, which the tests use. A change to a copied file
is a pull request in the kit: see "Changing a file that comes from the kit" in `AGENTS.shared.md`.

## Status

This is the first version. It holds the files as tooling-agenda has them, with the service name and the
variable prefix taken out, and the sync. Not yet here: the Action that opens a sync pull request, the CI
job that runs the check in each repository, the extension points for what a repository needs in its own
form, and `pr-preflight.sh`. See the tracking issue.

CI workflows are not in the kit. The four of tooling-agenda cannot be shared as they are: the runner
labels, the `subversion` and LDAP packages and the minutes corpus belong to a service, and a workflow
cannot read `devkit.conf`. Each service keeps its own until there is a way to share them.

What still belongs to tooling-agenda, and has to be made general:

- `.claude/settings.json`: `Read(./agenda.yaml)`, and the `make container-minutes-reading` entries. They
  stay while there is no way for a service to add to the file, and do no harm in another repository.
- `scripts/ci/verify.py`: `MINUTES_CORPUS` and the `corpus` stage, and the frontend fixtures under
  `tests/data`.
- `AGENTS.shared.md` names the nightly workflow of the behaviour record, which a service has to keep.
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
