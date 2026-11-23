# 0005: The kit's tests stay in the kit

Status: accepted. Implemented in apache/tooling-devkit#9 (merged 2026-11-22). The tests that read a service's
`Makefile` had left the kit in apache/tooling-devkit#10 (0008).

## Context

The tests of the kit's scripts were copied to each service with the scripts. Applying the kit to
tooling-secretary-records in a scratch copy showed what that costs. The test files were 5,742 of the 16,191
lines the sync handed over. They asserted the names of a service called `devkit`, so they failed in any
other repository, and some read the service's own `Makefile` or `.gitignore`. A copy of a script is
byte-identical to what the kit's CI ran the tests against, and the check keeps it so. A copy of the tests
could only add the differences of a service's environment.

## Decision

- The tests of the kit's scripts are the kit's own: `scripts/*.test.sh`, `scripts/ci/*.test.sh`,
  `.claude/hooks/guard-bash.test.sh` and `tests/`. The kit's CI runs them, and `devkit.files` lists none.
  `scripts/devkit-files.test.sh` fails if one is listed.
- A test of a service's own files, such as the recipes of its `Makefile`, belongs to the service.

## Consequences

- A repository deletes its copies of the kit's script tests when it takes the kit, and keeps the tests of
  its own wiring.
- The kit has no test that reads a service's `Makefile`: two in `test_fast_stage.py` and a section of
  `container-size.test.sh` were removed in apache/tooling-devkit#10, and a service keeps its own versions.

## Not done

- **Making the tests independent of the service name,** and skipping the sections that read a Makefile. It
  was done first, and dropped: it kept the tests in every repository to fix a problem that only exists
  because they are there.
