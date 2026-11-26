#!/bin/sh
# devkit.mk, the targets a service's Makefile includes: in a service of its own, built here, with the kit's
# scripts it reads. Kit only.
#
# What it holds: a plain `make` runs the service's first target wherever the include goes, a value the
# service sets before the include is the one the targets use and one in the environment is not, the include
# is found after another include and from another directory, the keep container is named for the checkout
# the Makefile is in, and a service that defines none of the fragment's targets gets no warning from make.

set -euf

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH='' cd -- "$here/.." && pwd)

# What make takes from the environment, which a run here must not: each would answer for the fragment.
unset MAKEFLAGS MAKEFILES PYTEST_WORKERS PYTEST_WORKERS_MAX DEVKIT_SIZE_WORKERS ASSETS_MANIFEST || true

failures=0
fail() {
    echo "FAIL: $1" >&2
    failures=$((failures + 1))
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# A service: the fragment, devkit.conf and checkout-id.sh, which the fragment reads as it is read, and a
# Makefile of its own. `$1` goes before the include, `$2` after it, `$3` names the directory. No .git
# directory, so the checkout is not the primary one and its suffix is the directory's name.
service() {
    dir="$work/$3"
    mkdir -p "$dir/scripts"
    cp "$root/devkit.mk" "$dir/devkit.mk"
    cp "$root/scripts/checkout-id.sh" "$dir/scripts/checkout-id.sh"
    printf 'DEVKIT_SERVICE=svc\n' >"$dir/devkit.conf"
    printf '%s\ninclude $(dir $(firstword $(MAKEFILE_LIST)))devkit.mk\n%s\n' "$1" "$2" >"$dir/Makefile"
    printf '%s\n' "$dir"
}

dry() {
    make -n -s --no-print-directory "$@" 2>&1
}

own='init:
	@echo the service first'

# The default goal is the service's, with the include before its first target and after it.
for where in before after; do
    if [ "$where" = before ]; then dir=$(service "" "$own" "$where"); else dir=$(service "$own" "" "$where"); fi
    said=$(dry -C "$dir") || fail "include $where: a plain make failed: $said"
    [ "$said" = "echo the service first" ] || fail "include $where: a plain make runs something else: $said"
done

# A value set before the include is the one the targets use; without one, the fragment's; and one in the
# environment is not taken.
dir=$(service 'PYTEST_WORKERS_MAX := 3' "$own" capped)
said=$(dry -C "$dir" container-test)
[ "$said" = "DEVKIT_SIZE_WORKERS=3 scripts/container.sh make test" ] ||
    fail "PYTEST_WORKERS_MAX set by the service is not what container-test sizes to: $said"
dir=$(service "" "$own" svc-topic)
said=$(dry -C "$dir" container-test)
[ "$said" = "DEVKIT_SIZE_WORKERS=6 scripts/container.sh make test" ] ||
    fail "without a PYTEST_WORKERS_MAX of the service, container-test is not sized to 6: $said"
said=$(PYTEST_WORKERS_MAX=2 dry -C "$dir" container-test)
[ "$said" = "DEVKIT_SIZE_WORKERS=6 scripts/container.sh make test" ] ||
    fail "PYTEST_WORKERS_MAX from the environment changed what container-test sizes to: $said"

# The frontend e2e-test-host builds first is the one the service named before the include.
manifest=$(service 'ASSETS_MANIFEST := built/manifest.json
built/manifest.json:
	@echo build the frontend' "" manifest)
said=$(dry -C "$manifest" e2e-test-host)
case $said in
"echo build the frontend"*"rm -rf state-e2e"*) ;;
*) fail "e2e-test-host does not build the frontend the service named first: $said" ;;
esac

# The fast stage, and the record of a full run that it reads.
said=$(dry -C "$dir" test-fast FAST_BASE=HEAD PYTEST_WORKERS=2)
[ "$said" = "uv run python scripts/ci/fast_stage.py run --base HEAD -- -n 2" ] ||
    fail "test-fast does not run the fast stage with its base and workers: $said"
said=$(dry -C "$dir" test-python)
case $said in
*"fast_stage.py begin python"*"--junitxml=state/fast-stage/junit.xml"*"fast_stage.py record"*"fast_stage.py passed python"*) ;;
*) fail "test-python does not record its run for the fast stage: $said" ;;
esac

# The keep container is named for the checkout the Makefile is in: from that directory, and with -f from
# another one.
name='DEVKIT_CONTAINER_NAME=svc-keep-svc-topic '
said=$(dry -C "$dir" container-keep)
case $said in
*"$name"*) ;;
*) fail "a plain make does not name the keep container for its checkout: $said" ;;
esac
said=$(cd "$work" && dry -f "$dir/Makefile" container-keep) || fail "make -f from elsewhere failed: $said"
case $said in
*"$name"*) ;;
*) fail "make -f from elsewhere does not name the keep container for the Makefile's checkout: $said" ;;
esac

# Another include before this one does not move where the fragment is looked for.
included=$(service 'include $(dir $(firstword $(MAKEFILE_LIST)))scripts/local/extra.mk' "$own" included)
mkdir -p "$included/scripts/local" && : >"$included/scripts/local/extra.mk"
said=$(dry -C "$included" check) || fail "an include before the fragment's moved where it is looked for: $said"

# Nothing on stderr: no warning about a recipe defined twice, and nothing the fragment could not read.
err=$(make -n -C "$dir" check 2>&1 >/dev/null)
[ -z "$err" ] || fail "make said something on stderr for a service that defines none of the fragment's targets: $err"

# A service that defines one of the fragment's targets again is warned, which is what keeps it from doing so.
dir=$(service "" "$own
check:
	@echo mine" twice)
err=$(make -n -C "$dir" check 2>&1 >/dev/null)
case $err in
*"overriding recipe for target"*"check"*) ;;
*) fail "a target defined again in the service gave no warning: $err" ;;
esac

# The gate's Python tests: the selection, and the whole suite where it answers 10. A stand-in `uv` notes
# each call, and answers the selection with GATE_STATUS.
mkdir -p "$work/bin"
cat >"$work/bin/uv" <<'STUB'
#!/bin/sh
echo "$*" >>"$UV_LOG"
case "$*" in *--gate*) exit "${GATE_STATUS:-0}" ;; esac
STUB
chmod +x "$work/bin/uv"
selected() {
    : >"$work/uv.log"
    status=0
    PATH="$work/bin:$PATH" UV_LOG="$work/uv.log" GATE_STATUS=$1 make -s --no-print-directory -C "$dir" \
        test-python-selected PYTEST_WORKERS=2 >/dev/null 2>&1 || status=$?
}
selected 0
[ "$status" -eq 0 ] || fail "test-python-selected fails where the selection passed"
grep -q -- '--gate -- -n 2' "$work/uv.log" || fail "test-python-selected does not run the gate's selection"
grep -q '^run pytest' "$work/uv.log" && fail "test-python-selected runs the suite where the selection passed"
selected 1
[ "$status" -ne 0 ] || fail "test-python-selected passes where the selection failed"
grep -q '^run pytest' "$work/uv.log" && fail "test-python-selected runs the suite where the selection failed"
selected 10
[ "$status" -eq 0 ] || fail "test-python-selected fails where the whole suite passed"
grep -q '^run pytest -n 2' "$work/uv.log" || fail "test-python-selected does not run the whole suite for a 10"
# verify.py keys a stage on `make -n`: that must print the recipe and run none of it
: >"$work/uv.log"
PATH="$work/bin:$PATH" UV_LOG="$work/uv.log" GATE_STATUS=10 make -n -s -C "$dir" test-python-selected >/dev/null 2>&1
[ ! -s "$work/uv.log" ] || fail "make -n test-python-selected runs what it should only print: $(cat "$work/uv.log")"

if [ "$failures" -gt 0 ]; then
    echo "$failures check(s) failed" >&2
    exit 1
fi
echo "devkit.mk: all checks passed"
