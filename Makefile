# How the kit's own tests run, on a machine and in CI. A kit-only file: a service has a Makefile of
# its own, with its own targets, and `devkit.files` does not list this one.
#
#   make test           everything below
#   make test-shell     the shell tests: the guard's, and those of the scripts
#   make test-python    the Python tests, and the scripts of scripts/ci compile and import
#
# The shell tests need `sh`, `git`, `flock` and the usual Unix tools. The Python setup is
# pyproject.toml and uv.lock, run by the uv that .tool-versions names, on the Python of
# .python-version.

SHELL_TESTS = .claude/hooks/guard-bash.test.sh $(wildcard scripts/*.test.sh scripts/ci/*.test.sh)

# What scripts/ci holds that other files import: each has to import with nothing but the standard
# library, since that is all the kit's scripts may need.
CI_MODULES = $(basename $(notdir $(wildcard scripts/ci/*.py)))

.PHONY: test test-shell test-python

test: test-shell test-python

test-shell:
	@failed=0; \
	for t in $(SHELL_TESTS); do \
		sh "$$t" || { echo "FAILED: $$t" >&2; failed=1; }; \
	done; \
	exit $$failed

test-python:
	uv run --frozen pytest -q -rs -p no:cacheprovider
	uv run --frozen python -I -m py_compile $(wildcard scripts/ci/*.py)
	cd scripts/ci && uv run --frozen --project ../.. python -I -c \
		"import sys; sys.path.insert(0, '.'); [__import__(name) for name in sys.argv[1:]]" $(CI_MODULES)
	@find scripts tests -name __pycache__ -type d -prune -exec rm -rf {} +
