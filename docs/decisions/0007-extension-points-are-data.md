# 0007: What a service adds is data it owns; the first is `scripts/local/verify.toml`

Status: accepted. Implemented for the gate in apache/tooling-devkit#11 (open when this was written).

## Context

A shared file that must differ a little per service cannot be edited in the copy (0001). `verify.py` was a
gate engine with the stages, inputs and settings of tooling-agenda written in it as Python constants.

## Decision

A shared file that needs something from the service reads a file the service owns, as data. For the gate it
is `scripts/local/verify.toml`, read with `tomllib`:

- the stages: the files each reads, whether it reads the Makefile, and which is the longest;
- the settings that change what a stage checks;
- what else a stage depends on: a file, the trailers of the branch's commits, or what a command prints.

Nothing of the repository is imported to run the gate, and a file that cannot be run is refused with every
reason at once. `PYTEST_WORKERS`, `DEVKIT_PYTHON` and `PYTEST_ADDOPTS` stay in the engine, because the kit's own
scripts set them.

## Consequences

- On tooling-agenda's tree, with its constants written as a `verify.toml`, five of the six stage keys are
  byte-equal to the old ones. The sixth, `test-python`, changes because the minutes corpus is a command now:
  that stage runs once more.
- The same shape is wanted for the other things a service adds: rules for `pr-preflight.sh`, extra rules for
  the guard (`.claude/guard.local`, which may add a restriction and never remove one), and additions to
  `.claude/settings.json`. None is built.

## Not done

- **A Python module the service owns,** imported by the engine. It is the most flexible, but the gate would
  run the repository's own code, and a mistake in it is a traceback.
- **The constants kept in the kit's copy.** Every service would edit a copy, and the engine would drift.
