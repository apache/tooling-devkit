# Design of the kit

Why the kit is the way it is: one section for each decision, saying what was decided, why, what it costs,
and what was not done instead. This file is the kit's own and is not in `devkit.files`; the sync never copies
it. What is still open is in the tracking issue,
[apache/tooling-migration#50](https://github.com/apache/tooling-migration/issues/50).

A new decision gets the next number and a section here, in the pull request that makes the change. A decision
that is replaced stays, with a line that says what replaced it. Say only what was checked.

1. [One source, copies in the services](#1-one-source-copies-in-the-services)
2. [Names: `DEVKIT_` and `devkit.conf`](#2-names-devkit_-and-devkitconf)
3. [The sync](#3-the-sync)
4. [The guard stands down only where it lives at `/run/<service>`](#4-the-guard-stands-down-only-where-it-lives-at-runservice)
5. [The tests stay in the kit](#5-the-tests-stay-in-the-kit)
6. [CI workflows stay in the services](#6-ci-workflows-stay-in-the-services)
7. [What a service adds is data it owns](#7-what-a-service-adds-is-data-it-owns)
8. [The kit's own Python setup](#8-the-kits-own-python-setup)
9. [Seeded from one repository, made general by applying it to others](#9-seeded-from-one-repository-made-general-by-applying-it-to-others)
10. [A file of the kit refers to nothing outside the kit](#10-a-file-of-the-kit-refers-to-nothing-outside-the-kit)
11. [What a make wrapper may be given](#11-what-a-make-wrapper-may-be-given)
12. [A service adds permissions in a file, merged at sync](#12-a-service-adds-permissions-in-a-file-merged-at-sync)
13. [The shared make targets are a fragment the service includes](#13-the-shared-make-targets-are-a-fragment-the-service-includes)

## 1. One source, copies in the services

Accepted by the Tooling PMC on 2026-11-19 (D-18 in apache/tooling-migration). First version:
apache/tooling-devkit#1.

**Why.** Each Tooling repository carried its own copy of the agent rules, the Bash guard, the commands, the
scripts and the CI workflows, and the copies drifted in both directions. A fix to the guard reached another
repository as a pull request that was open for eleven days, had fallen 116 commits behind and conflicted
with its target. By then there were three versions of the guard, of 1,300 to 1,556 lines.

**Decided.** `apache/tooling-devkit` holds the shared files. A service holds copies at the paths it already
uses, so that a clone has the guard and the rules with no step. The copies are kept as the kit has them (3).
A change to a copied file is a pull request in the kit, reviewed by the Tooling PMC.

**Costs.** A repository cannot change a shared file for itself. What differs on purpose has a place of its own:
a value in `devkit.conf`, an extension point (7), or an override with an issue and a date (3).

**Not done.** Git submodules: a clone without `--recursive` has no guard and no rules. A Claude Code plugin
or skill alone: each person has to install it, it cannot carry rules that are always loaded, and a guard that
only some people have is not a guard (a skill for the work agents do is planned in addition). Templates with
placeholders: a filled-in copy is not the file the kit tested.

## 2. Names: `DEVKIT_` and `devkit.conf`

Accepted. apache/tooling-devkit#1.

**Why.** The scripts read `BAT_MEMORY` in tooling-agenda and `SR_MEMORY` in tooling-secretary-records, and name
images, volumes and containers after the service. About 430 lines of the shared files held the prefix. A
prefix taken from a config file would need an indirection (`eval "\${${PREFIX}_MEMORY:-}"`) in every one of
them, and the guard refuses `eval`.

**Decided.** One neutral prefix, `DEVKIT_`, for every variable the kit's scripts read or set, so the shared
files are the same bytes everywhere. The `devkit.conf` of a repository holds `DEVKIT_SERVICE` and
`DEVKIT_REPOSITORY` as `KEY=value` lines, which scripts read with `sed` and never source: the guard reads it
too, and must not run a file of the repository it guards. The service name gives the image, volume, container
and network names and the working directory `/run/<service>`; it is lower case letters, digits, `-` and `_`,
starting with a letter or a digit, because it ends up in names, `sed` patterns and a path. Names that need no
service are neutral: temporary prefixes, lock and stamp files, labels.

**Costs.** A repository renames the variables the kit reads or sets when it takes the kit, the isx template
sets `DEVKIT_ISOLATED=1` instead of its own name, and its volumes are named after `DEVKIT_SERVICE`. The
application's own variables stay.

**Not done.** A prefix from the config (the indirection above). Both names for a while (an alias layer to
keep, for a rename that happens once).

## 3. The sync

Accepted. apache/tooling-devkit#4.

**Why.** Copying files without a record of where they came from, or a way to tell that a copy was edited, is
how the drift started.

**Decided.**

- `devkit.files` in the kit lists what a service may take: a path, or `source destination`. What the kit holds
  and does not list is the kit's own.
- `devkit.lock` in a service holds the kit commit it took, and `override <path> <issue> until <YYYY-MM-DD>`
  lines for a copy that differs on purpose. The sync rewrites only the `commit` line.
- `scripts/devkit-sync.sh <ref>` copies the listed files at that commit and writes the commit to the lock.
  `--check` compares each file with the kit at the locked commit, prints each override, and fails on drift, a
  missing file, an override past its day, and a lock that is not usable. It is one script.
- `DEVKIT_SKIP` in `devkit.conf` names what a repository keeps as its own. It lists what is left out, not what
  is taken, so a file the kit adds reaches every repository by default.
- The first line of a copy says where to change it. It is in the kit's own file, so a copy stays
  byte-identical. A file that cannot carry a comment (`.claude/settings.json`, the license template) has none,
  and the check covers it all the same. `.claude/settings.json` is the one file a sync builds: see 12.
- Files are compared with `git diff --no-index`, which also sees a lost executable bit: `cmp` is not in every
  container, and `git` is needed anyway. The check reads the real kit at the locked commit, not hashes in the
  lock, because a hash edited together with its file would hide the drift.

**Costs.** The first copy of `devkit-sync.sh` is made by hand, and `<ref>` is a branch, a tag or a full commit
id: git does not fetch an abbreviated one. A kit that lists a path the sync must not write (absolute, upward,
inside `.git`, or the service's own `devkit.conf` or `devkit.lock`) is refused before anything is copied. The
check is not yet in any repository's CI and nothing opens a sync pull request yet: both need a repository that
has taken the kit first.

**Not done.** A `files:` list of what a repository takes: a new kit file would reach nobody until each
repository added it, and `devkit.conf` is `KEY=value`, which holds no list. A separate drift-check script.

## 4. The guard stands down only where it lives at `/run/<service>`

Accepted. Found by an adversarial pass before apache/tooling-devkit#1 was merged, and fixed in it.

**Why.** The guard refuses commands that run the toolchain on the host, and has to stand down inside the dev
container, where running `uv` and `yarn` is the point. It first did so when `/run/<service>` existed, with the
service read from `devkit.conf`. But `devkit.conf` is the repository's file to write: a service of `.`, `..`,
`/` or `user` named a directory that exists on any host, and the guard allowed `uv run pytest`. So did a
duplicated key whose first line was `.`.

**Decided.** The guard stands down only if the directory two levels above the guard itself resolves to
`/run/<service>`, which is where the container mounts the working tree and nowhere else, and only for a name
that is one (2). With no `devkit.conf`, or a name that is not valid, it stays on: the safe answer to "am I
already inside". `checkout-id.sh` and `behaviour_pulls.py` apply the same rule to the name.

**Costs.** Nothing a repository writes into its own files can switch the guard off. The guard test runs it from
a copy in a directory of its own with the override removed, for each bad name and for no file. That it does
stand down at `/run/<service>` is not tried: nothing makes a directory there.

**Not done.** Testing for `/run/<service>` as a path, which is what the first version did.

## 5. The tests stay in the kit

Accepted. apache/tooling-devkit#9 (merged 2026-11-22). The tests that read a service's `Makefile` had left the
kit in apache/tooling-devkit#10 (see 8).

**Why.** The tests of the kit's scripts were copied to each service with the scripts. Applying the kit to
tooling-secretary-records in a scratch copy showed the cost. The test files were 5,742 of the 16,191 lines the
sync handed over. They asserted the names of a service called `devkit`, so they failed in any other
repository, and some read the service's own `Makefile` or `.gitignore`. A copy of a script is byte-identical to
what the kit's CI ran the tests against, and the check keeps it so. A copy of the tests could only add the
differences of a service's environment.

**Decided.** The tests of the kit's scripts are the kit's own: `scripts/*.test.sh`, `scripts/ci/*.test.sh`,
`.claude/hooks/guard-bash.test.sh` and `tests/`. The kit's CI runs them, and `devkit.files` lists none;
`scripts/devkit-files.test.sh` fails if one is listed. A test of a service's own files, such as the recipes of
its `Makefile`, belongs to the service.

**Costs.** A repository deletes its copies of the kit's script tests when it takes the kit, and keeps the tests
of its own wiring. The kit has no test that reads a service's `Makefile`: two in `test_fast_stage.py` and a
section of `container-size.test.sh` were removed, and a service keeps its own versions.

**Not done.** Making the tests independent of the service name and skipping the sections that read a
Makefile. That was done first and dropped: it kept the tests in every repository to fix a problem that only
exists because they are there.

## 6. CI workflows stay in the services

Accepted. apache/tooling-devkit#5 (merged 2026-11-22). The way to share them is open.

**Why.** The four workflows of tooling-agenda were in the first version of the kit. Dependabot updates the
pinned actions in the `.github/workflows/` of each repository, so a copy would differ from the kit after every
update, and the drift check would fail. The workflows also hold what belongs to one service: the `subversion`
and LDAP packages and the minutes corpus, which a workflow cannot take from `devkit.conf`. The ASF
self-hosted runner labels are only tooling-agenda's, because it is the private repository; the public ones use
hosted runners.

**Decided.** The workflows leave the kit and `devkit.files`, and each service keeps its own. The kit has a
workflow of its own, `.github/workflows/test.yml`, which runs `make test` (8), and `.github/dependabot.yml`
keeps its pins current.

**Costs.** The services' workflows can drift from each other, and nothing checks that they do not. Only the
runner labels are one repository's business: the dependabot drift and the service-specific steps are why they
stay out.

The drift check (3) runs in a workflow each service keeps, `.github/workflows/devkit.yml`, on every pull
request and push to `main`: a checkout and `sh scripts/devkit-sync.sh --check`, which needs only `sh` and
`git`. A copy edited in a service, or an override past its day, fails it there, and not only on a machine
that ran the check by hand.

**Not done.** Reusable workflows with inputs, pinned by commit id: the likely way to share them, so that only
the kit's copy is updated by dependabot and a service calls it. Open in the tracking issue.

## 7. What a service adds is data it owns

Accepted. Implemented for the gate in apache/tooling-devkit#11 (merged 2026-11-23), and for the pre-PR checklist
in the change that follows it.

**Why.** A shared file that must differ a little per service cannot be edited in the copy (1). `verify.py` was
a gate engine with the stages, inputs and settings of tooling-agenda written in it as Python constants.

**Decided.** A shared file that needs something from the service reads a file the service owns, as data. For
the gate it is `scripts/local/verify.toml`, read with `tomllib`: the stages (the files each reads, whether it
reads the Makefile, which is the longest), the settings that change what a stage checks, and what else a stage
depends on (a file, the trailers of the branch's commits, or what a command prints). Nothing of the repository
is imported to run the gate, and a file that cannot be run is refused with every reason at once.
`PYTEST_WORKERS`, `DEVKIT_PYTHON` and `PYTEST_ADDOPTS` stay in the engine, because the kit's own scripts set them.

The pre-PR checklist (`scripts/pr-preflight.sh`) has the same shape: the machinery and the scan for who else is in
the same files are the kit's, and the rules of a repository are `scripts/local/preflight.toml`, each with a
title, the patterns that make it apply (to the paths a branch changes or to those it adds), optionally a pattern
the lines it adds must match, and the lines it prints. The rules of the kit that hold everywhere stay in the
script. The script runs on a host with `sh` and `git`, so a small standard-library helper
(`scripts/ci/preflight_rules.py`) checks the file and hands the rules to the shell as lines. The helper runs
only where there is a file.

The behaviour comparison has the third shape: `scripts/local/behaviour.toml` adds globs to the lists of the kit
(`everything_when`, the paths whose change records everything; `harness_files`, what the record is made with)
and prefixes to the tests that run whole (`[whole]`). `scripts/ci/behaviour_rules.py` reads it, and only adds:
a glob or a prefix that the kit has is refused, so a copy of the kit's list cannot go stale in a service. The
kit's lists are the ones that hold in every service; `schema/**`, `tests/test-config.yaml`, `tests/data/wc/*`
and `tests/data/static_assets/*` were tooling-agenda's, and the `task` and `artefact` tests too. The tests of
the comparison (`tests/test_behaviour_*.py`) are the kit's. The tests of a service's own harness, such as
`tests/behaviour/executed.py`, stay in the service.

The fast stage has the same shape: `scripts/local/fast_stage.toml` adds `broad_packages` (the packages under
`app/` whose tests are too many to select by one module) and `[full_when]` (paths that reach every test, each
with the reason). `scripts/ci/fast_stage_rules.py` reads it, and only adds: a glob the kit has is refused. The
kit keeps the globs that hold in every service (the dependency files, `tests/conftest.py`, the fixture data,
the behaviour harness, `app/__init__.py`); `tests/test-config.yaml`, `schema/**`, `app/webapp.py`, `server.py`
and the migrations were tooling-agenda's, as was the list of broad packages (`api`, `models`, `actions`, `md`).
A service without the file has no broad package, so a change to a module selects the tests of its package:
more tests, not fewer. A file the stage cannot use stops it before it selects anything, since a selection made
without the rules of the service could leave out the test a change breaks.

**Costs.** On tooling-agenda's tree, with its constants written as a `verify.toml`, five of the six stage keys
are byte-equal to the old ones; the sixth, `test-python`, changes because the minutes corpus is a command now,
and that stage runs once more. With tooling-agenda's seven rules written as a `preflight.toml`, the new script
printed the same as its old one on 13 of 14 kinds of change; on the fourteenth the old script missed a new
uncommitted helper file beside a component, and the new one reads it, as it does once it is committed. The three lists of tooling-agenda's behaviour scripts are the kit's plus a `behaviour.toml` of two `everything_when` globs, three `harness_files` globs and two `[whole]` prefixes, with nothing missing on either side (compared by loading both sets of scripts). A
repository with a rules file needs Python 3.11 or newer wherever it runs the checklist, and the script refuses
to run without it: a checklist that dropped the rules it could not read would look complete and not be. The
same shape is wanted for extra rules for the guard (`.claude/guard.local`, which may add a restriction and never remove one). It is not built. Additions to `.claude/settings.json` are built: see 12.

**Not done.** A Python module the service owns, imported by the engine: the most flexible, but the gate would
run the repository's own code, and a mistake in it is a traceback. The constants kept in the kit's copy: every
service would edit a copy, and the engine would drift.

## 8. The kit's own Python setup

Accepted. apache/tooling-devkit#10 (merged 2026-11-22).

**Why.** The setup of the kit's Python tests lived in the test workflow: a `pip install` of two pinned
packages, and a list of scripts to import that had fallen behind the scripts.

**Decided.** `pyproject.toml` has a `test` group, `pytest` and `pytest-xdist`, locked in `uv.lock`; the tests
of the selection audit run a real `pytest -n 2`, which is why the second is there. `.tool-versions` names the
uv and `.python-version` the Python, as in the services. `make test` runs the shell tests and the Python tests,
and compiles and imports every script of `scripts/ci` by a glob. The workflow runs `make test`, and dependabot
updates the lock and the action pins. These files are the kit's own and are not in `devkit.files`: a service
has its own.

**Costs.** The kit has a `Makefile`, so a test that reads a service's `Makefile` cannot hold in it (5).

**Not done.** Keeping the setup in the workflow: it could not be run on a machine, and it was not defined where
a reader of the repository would look.

**Lint.** `make lint`, part of `make test` and so of the kit's CI, runs the hooks of the services that act on the
shared files, over every file: `.pre-commit-config.yaml` has the same hooks at the same versions and with the same
settings (whitespace and end of file, the license header, markdownlint, shellcheck over the scripts a service takes,
zizmor, `ruff check` and `ruff format`), and `ruff` is pinned to the version the services lock. The kit's files had
been written in tooling-agenda, then renamed, and when tooling-secretary-records took them its `make check` failed on
one SC2154, one SC2249, one SC1007, the format of one file and one ruff TC003; a second run found a blank line that
markdownlint adds to `AGENTS.shared.md`, which the hook of a service rewrites into drift (1) in a copy it cannot
change. A file that fails a hook of a service is a drift that the service cannot fix in its copy.

## 9. Seeded from one repository, made general by applying it to others

Accepted. Done for the first version in apache/tooling-devkit#1, and again in apache/tooling-devkit#3 and
apache/tooling-devkit#6.

**Why.** Four repositories held the shared files, and the proposal said to take the best version of each. They
did not all differ in the same direction, and tooling-agenda was the one that kept moving.

**Decided.** Seed from the repository that has the latest version, tooling-agenda, in steps a review can
follow: the files as they were, the rename to `DEVKIT_` (2), the names taken from `devkit.conf`, then the
documents. A change that lands in tooling-agenda later comes in as its own pull request. Find what is not
general by applying the kit to another repository in a scratch copy and running its tests, before any
repository is changed. That found, in tooling-secretary-records, the tests that assumed a service called
`devkit` (5), and three files where its version was the more general one: `quality_meters.py` tolerates a
tree without the files a meter reads, `apt-install.sh` checks that the metadata answer is a region, and
`production_import.py` imports a type under `TYPE_CHECKING`. They were taken into the kit. A new test is shown
failing first: one that has only ever passed has not been shown to test anything.

**Costs.** A change to a copied file in a service is lost at the next sync unless it was made in the kit.

**Not done.** A merge of all four repositories before anything was published: one large review of files whose
differences were mostly names.

## 10. A file of the kit refers to nothing outside the kit

Accepted. apache/tooling-devkit#5.

**Why.** The files came from tooling-agenda with comments that cited its issues and pull requests, dates, the
names of people, and the story of how a rule came to be. In the kit that context is gone: a reference such as
`#729` to another repository is a number nobody can follow, and a comment that says "this used to be a bare
`except`" describes a version nobody can reach.

**Decided.** A comment says what the code does and why, and warns of what an edit could bring back; it does not
tell how it got that way. A file does not cite an issue or a pull request of another repository, a date of an
incident, or a person. A reference to the tracking issue of the kit, or to this file, is fine. A measurement
that explains a constant stays, with what it was measured on. Examples use neutral names: `tooling-service#12`,
`@<github-username>`.

**Costs.** 49 references were rewritten. Outside comments, only docstrings in five Python files and two
sentences that `pr-review.sh` prints changed, which was checked line by line. A file ported from a service is
cleaned the same way before it comes in.

**Not done.** Keeping the references as a trail back to the services: the history is in the services.

## 11. What a make wrapper may be given

Accepted. apache/tooling-devkit, the change that adds `scripts/guard-names.test.sh`.

**Why.** The guard refuses everything on a make line but the target and the `NAME=value` pairs it lists, and its
comment says the list is "the names the scripts read, and no others". Nothing held it to that. The list of
tooling-agenda and the one of tooling-secretary-records differed by three names, and counting what the kit's
scripts use showed 36 `DEVKIT_` names, of which the guard lists 19. Every listed name is read by a script. Of
the 17 that are not listed, one has a rule of its own and the others should not be.

**Decided.**

- The list is the kit's and is closed. It holds two kinds of name: the `DEVKIT_` settings a person changes
  for one run of a wrapper, and the make variables of the shared targets (`KEEP_PORT`, `QUALITY_REF`, `ARGS` and
  the like). A value is a plain value, except where a name has a shape of its own (`ARGS`, `FILTER`, `KEEP_CMD`,
  `DEVKIT_RUNTIME`).
- A `DEVKIT_` name that a script uses is on the list, or is declared not to be, with the reason: it is the guard's
  own switch, it is a program or a place the script runs or fetches from, it is a script's own setting given to it
  directly, it is read from `devkit.conf`, it is a hook for the kit's tests, or a script or CI sets it for what
  it starts.
- `scripts/guard-names.test.sh` holds this. It fails when a script starts to use a name that nobody has decided
  on, when a name is on both lists or on neither, when a name is on either list and no script uses it, when the
  guard refuses a listed name, allows one declared as not, or accepts a value that is more than a plain value.
- The three names in the list of tooling-secretary-records (`APT_CACHE`, `E2E` and `E2E_EXTERNAL_SERVER`) are
  not added. The first is set by a CI action, and the other two are read by that repository's own files, not by
  a script of the kit.

**Costs.** A variable of a service's own that has to be given on a make line needs a change to the kit's list.
That is a pull request to the kit, reviewed by the Tooling PMC, which is right: it widens what an agent may pass.

**Not done.** A list that a repository writes, in `devkit.conf` or a file of its own: a name it could add is
`SHELL` or `PATH`, whose plain value runs code, which is the reason of 4. A list read from the repository's
`Makefile`, for the same reason. A pattern such as `DEVKIT_*` in place of the names: a pattern is what let
`DEVKIT_X$(...)` and `DEVKIT_X!` through.

## 12. A service adds permissions in a file, merged at sync

**Decided.** `.claude/settings.json` of the kit holds only what every service needs. A service that needs
more writes `.claude/settings.additions.json`, with a `permissions` object that has `allow`, `deny` or `ask`,
each a list of non-empty strings. `scripts/devkit-sync.sh` writes `.claude/settings.json` as the kit's file
with the additions put after the entries of the kit, each entry once. The service owns the additions file and
the sync never changes it.

**Why.** Claude Code reads one committed project file, so the additions have to be in that file. The first
entries that were tooling-agenda's own (`Read(./agenda.yaml)` and two `make container-minutes-reading`
targets) were in the kit only because the file had no other place for them. They are not in the kit now.

- Only `permissions` can be added. The `hooks` are the kit's: an addition there could turn the guard off. An
  allow entry only skips a prompt, and the guard still runs; a deny entry of the kit stays, because deny
  beats allow.
- The check builds the same file from the kit at the locked commit and the additions, and compares it with the
  copy. An edit of the copy is drift, and so is a change of the additions that was not synced. The message
  names the additions file.
- The merge code is in the sync script, so the sync runs no code it fetched. It needs `python3`, and only
  where an additions file exists; the name of the program can be set with `DEVKIT_SYNC_PYTHON`, which the
  tests use. A file the sync cannot use stops it, with every reason named.
- `DEVKIT_SKIP` of `.claude/settings.json` ignores the additions file, as it does for any file.
- A repository must not list `.claude/settings.additions.json` in `devkit.files`; the sync refuses it.

**Not done.** A second settings file for the service (`settings.local.json` is personal and ignored). Merging
`hooks` or `env`. An additions file in the kit's own format with a header: JSON has no comment.

## 13. The shared make targets are a fragment the service includes

**Why.** A script of the kit does nothing in a service that lacks the target that runs it. Each service kept
its own copy of the same targets, and the copies drifted: tooling-agenda's `test-python` recorded its run for
the fast stage and had `test-fast`, and its `quality-base` and `snapshot-base` shared a reading across
worktrees (`bases.py`); the three other services had none of that. The Makefiles of tooling-directory and
tooling-roster differed in one line, the name of the service in a comment.

**Decided.** `devkit.mk`, a kit file, holds every target that calls a kit script or is the same in every
service: `check`, `check-all`, `lint`, `test` and its halves with the record the fast stage reads, `test-fast`,
`pytest`, `test-coverage`, `verify`, the quality ratchet, the behaviour record, the `e2e-*` wrappers and the
`container-*` wrappers. A service's `Makefile` includes it, anchored on the Makefile
(`include $(dir $(firstword $(MAKEFILE_LIST)))devkit.mk`; the first word, since after another include the last
is that file), and keeps `init`, `build`, `certs`, `dev`, `run`,
`sync` and its own targets. The recipes are tooling-agenda's, which had the newest of each.

- A service sets `PYTEST_WORKERS_MAX` or `ASSETS_MANIFEST` in its `Makefile`, before the include: make reads
  `ASSETS_MANIFEST` where the fragment names it as a prerequisite, so a value set after is not seen. The
  fragment gives `PYTEST_WORKERS_MAX` 6 unless the Makefile set it, and does not take it from the environment,
  where the old Makefiles did not either; the command line still beats both.
- The fragment keeps the default goal as it found it, so a plain `make` runs the service's first target wherever
  the include goes.
- A service does not define a target of the fragment again: make warns, and runs the recipe it read last.
- The kit's scripts that read a change to the `Makefile` read one to `devkit.mk` the same way: it records
  everything in the behaviour comparison (`EVERYTHING_WHEN`), and the gate keys a stage on its recipe through
  `make -n` rather than on the file, so a comment in either reruns nothing.
- `scripts/devkit-mk.test.sh` builds a service of its own and holds each of these.

**Costs.** A service that needs a different recipe for a shared target has no extension point for it; it keeps
the file as its own with `DEVKIT_SKIP`, which gives up every later change of the kit to it. The three services
that took the fragment changed what `test-python`, `test-frontend`, `quality-base`, `snapshot-base`,
`container-test-coverage` and `container-test-py314` run, to tooling-agenda's recipes.

**Not done.** The whole `Makefile` as a kit file, with a service's targets in a `Makefile.local` it includes:
tooling-agenda's own targets and its `dev` on compose would have needed hooks in the kit, and a target defined
twice is a warning, not an error. Make variables in place of the recipes for each difference: there was no
difference left that the services needed.

## 14. A gate holds a slot without a container too, and runs one suite at a time

**Why.** On a host, a run of the whole suite takes a gate slot and is sized to the machine, so a second
session's gate waits rather than starting beside the first. Where `DEVKIT_ISOLATED=1`, `container.sh` ran the
command before it reached the sizing, so neither applied. Several sessions share one box as they share a host,
and their gates all started at once: on a 16-core box one gate alone took the load to 32. Inside one gate,
`verify.py` started every stage together, and two of a service's stages can each run its test suite.

**Decided.** `container.sh` sizes a run and takes its slot (`size_this_run`) before the isolated path runs the
command, which then holds the slot on descriptor 8 as `podman run` does, and is given the workers it was sized
for. It has no memory cap: there is no container to put one on. A stage of `verify.toml` may say it is
`heavy`; a heavy stage starts once the heavy stage before it has ended, the `longest` first. The other stages
still run beside them.

**Costs.** A box's gates now wait for one another, as a host's do. A gate whose heavy stages ran together runs
them one after the other, and takes longer by the shorter of them. A heavy stage computes whether it changed
before it waits, and a file edited while it waits is a change after the run, so nothing is recorded; it runs
again next time.

**Not done.** A cap on how many stages run at once: the light stages cost little, and it is the suites that
make the peak. Sizing the isolated slot by `MemAvailable`: the slots are sized by `MemTotal` on a host for the
reasons in `container-size.sh`, and the same reasons hold on a box.
