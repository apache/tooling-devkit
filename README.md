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
| `.claude/hooks/guard-bash.sh` | the guard that holds the rules in `AGENTS.shared.md` |
| `.claude/commands/` | the pre-PR adversarial pass, the end-to-end run and the screenshots |
| `.claude/settings.json` | the permission allowlist and the hook registration; a service adds permissions in `.claude/settings.additions.json` |
| `scripts/` | the container wrappers, the worktree scripts, the review reader and the CI helpers, among them the fast local test stage (`scripts/ci/fast_stage.py`) |
| `tests/` | the Python tests of the kit's scripts: the fast stage, the selection audit, the quality meters and the behaviour comparison |
| `.github/actions/` | the apt-install action |
| `.github/workflows/test.yml` | the kit's own CI: the shell tests, and the Python compiles |
| `docs/design.md` | why the kit is the way it is: a section for each design decision. The kit's own, not synced |
| `devkit.conf` | the names the shared files read: `DEVKIT_SERVICE`, `DEVKIT_REPOSITORY` |
| `devkit.files` | the files a service may take, with where each goes; the rest is the kit's own |
| `scripts/devkit-sync.sh` | copies those files at a commit, and checks that a copy is still as the kit has it |

The tests of the kit - `scripts/*.test.sh`, `scripts/ci/*.test.sh`, `.claude/hooks/guard-bash.test.sh` and
`tests/` - are the kit's own: the kit's CI runs them, and a service does not take them. A copy of a script is
byte-identical to what they ran against, and the drift check keeps it so.

A service repository has a `devkit.conf` of its own. The variables the shared files read start with
`DEVKIT_`, and the image, volume and container names take the service name from `devkit.conf`. Some files
still carry what belongs to tooling-agenda: see "Status".

## Taking the kit

A service repository keeps its own `devkit.conf` and `devkit.lock`. The first copy of
`scripts/devkit-sync.sh` is made by hand; after that:

```sh
scripts/devkit-sync.sh <ref>    # copy the files at <ref>, a branch, a tag or a full commit id, and write the commit to devkit.lock
scripts/devkit-sync.sh --check  # compare them with the kit at that commit
```

Nothing is committed for you. A repository that keeps a file as its own names it in `DEVKIT_SKIP` in
`devkit.conf`, paths separated by spaces. A copy that differs on purpose, for a time, goes in
`devkit.lock` with its issue and the day it ends:

```text
commit 0123456789abcdef0123456789abcdef01234567
override scripts/e2e-container.sh tooling-service#12 until 2026-12-31
```

The sync leaves an overridden file as it is, and the check prints each override and fails after its day.
`DEVKIT_SOURCE` names another place to fetch the kit from, which the tests use. A change to a copied file
is a pull request in the kit: see "Changing a file that comes from the kit" in `AGENTS.shared.md`.

## Status

The files come from tooling-agenda, with the service name and the variable prefix taken out. Not in the kit
yet: the Action that opens a sync pull request, the CI job that runs the check in each repository, the
extension points for what a repository needs in its own form, except the first four. See the tracking issue.

The first extension point is `scripts/local/verify.toml`, a file a repository owns, in which it names the
stages of its gate (`scripts/ci/verify.py`), the files and settings each reads, and what else they depend on.
The file is data: the gate reads it with `tomllib` and imports nothing of the repository. The format is in the
docstring of `verify.py`, and a file that cannot be run is refused with every reason at once.

The second is `scripts/local/preflight.toml`, in which a repository adds rules to the checklist of
`scripts/pr-preflight.sh`: a title, the paths that make a rule apply, and the lines it prints. A repository
without the file has the rules of the kit. Reading the file needs Python 3.11 or newer on the machine that runs
the script, and a file it cannot use stops the run. The format is in the docstring of
`scripts/ci/preflight_rules.py`.

The third is `.claude/settings.additions.json`, in which a repository adds permissions (`allow`, `deny`,
`ask`) to the allowlist of the kit. The sync merges them into `.claude/settings.json`: the entries of the kit
first, then those of the file, each once. Nothing else can be added, and the hooks stay as the kit has them. A
repository with the file needs Python 3.11 or newer where it runs the sync, and a file the sync cannot use is
refused with every reason at once. See `docs/design.md`, 12.

The fourth is `scripts/local/behaviour.toml`, in which a repository adds to what the behaviour comparison
(`scripts/ci/behaviour.py`) takes from the kit: globs of paths that make a change record everything
(`everything_when`), globs of what the record is made with (`harness_files`), and the tests whose parts run as
one (`[whole]`). The kit has the lists that hold everywhere; the file only adds to them. A file that cannot be
used is refused with every reason at once. The format is in the docstring of `scripts/ci/behaviour_rules.py`.

CI workflows are not in the kit. Dependabot updates the pinned actions in the `.github/workflows/` of each
repository, so a copy of a kit workflow would differ from the kit after every update, and the drift check
would fail. The four workflows of tooling-agenda also hold what belongs to one service: the `subversion`
and LDAP packages and the minutes corpus, which a workflow cannot take from `devkit.conf`. The ASF runner
labels are only tooling-agenda's, because it is private; the public repositories use hosted runners. Each
service keeps its own workflows until there is a way to share them.

What still belongs to tooling-agenda, and has to be made general:

- `AGENTS.shared.md` names the nightly workflow of the behaviour record, which a service has to keep.
- The variables that no script of the kit reads: the tests and the e2e specs of a service read
  `DEVKIT_E2E_URL`, `DEVKIT_E2E_HOST`, `DEVKIT_BEHAVIOUR_OUT` and others, so a service renames its own at
  the same time as it takes the kit.

## Tests

```sh
make test          # lint, the shell tests, the Python tests, and the scripts of scripts/ci compile and import
make lint          # `ruff format --check` and shellcheck, with the settings of the services' hooks
make test-shell
make test-python
```

The shell tests need `sh`, `git`, `flock` and the usual Unix tools. The Python setup is `pyproject.toml` and
`uv.lock`, run by the uv that `.tool-versions` names on the Python of `.python-version`; the CI of the kit
runs `make test`. The `Makefile`, `pyproject.toml`, `uv.lock` and `.tool-versions` belong to the kit and are
not in `devkit.files`.

The tests of the kit's scripts stay in the kit. The tests of a service's own files, such as the recipes of its
`Makefile`, are the service's to keep.

## License

Apache License 2.0. See `LICENSE`.
