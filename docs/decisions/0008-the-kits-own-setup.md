# 0008: The kit's own Python setup is a Makefile, `pyproject.toml` and `uv.lock`

Status: accepted. Implemented in apache/tooling-devkit#10 (merged 2026-11-22).

## Context

The setup of the kit's Python tests lived in the test workflow: a `pip install` of two pinned packages, and
a list of scripts to import that had fallen behind the scripts.

## Decision

- `pyproject.toml` has a `test` group, `pytest` and `pytest-xdist`, locked in `uv.lock`. The tests of the
  selection audit run a real `pytest -n 2`, which is why the second is there.
- `.tool-versions` names the uv, and `.python-version` the Python, as in the services.
- `make test` runs the shell tests and the Python tests, and compiles and imports every script of
  `scripts/ci`, by a glob. The workflow runs `make test`. Dependabot updates the lock and the action pins.
- The four files are the kit's own and are not in `devkit.files`: a service has its own.

## Consequences

- The kit has a `Makefile`, so a test that reads a service's `Makefile` cannot hold in it (0005).
- Nothing in the kit's setup is shared with a service. A service's setup is its own.

## Not done

- **Keeping the setup in the workflow.** It could not be run on a machine, and it was not defined anywhere a
  reader of the repository would look.
