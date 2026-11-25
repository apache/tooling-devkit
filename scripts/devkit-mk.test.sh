#!/bin/sh
# devkit.mk, the targets a service's Makefile includes: in a service of its own, built here, with the kit's
# scripts it reads. Kit only.
#
# What it holds: a plain `make` runs the service's first target wherever the include goes, a value the
# service sets before the include is the one the targets use, the include finds the fragment when make runs
# elsewhere, and a service that defines none of the fragment's targets gets no warning from make.

set -euf

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH='' cd -- "$here/.." && pwd)

failures=0
fail() {
    echo "FAIL: $1" >&2
    failures=$((failures + 1))
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# A service: the fragment, devkit.conf and checkout-id.sh, which the fragment reads as it is read, and a
# Makefile of its own. `$1` is what goes before the include, `$2` what goes after it.
service() {
    dir="$work/$3"
    mkdir -p "$dir/scripts"
    cp "$root/devkit.mk" "$dir/devkit.mk"
    cp "$root/scripts/checkout-id.sh" "$dir/scripts/checkout-id.sh"
    printf 'DEVKIT_SERVICE=svc\n' >"$dir/devkit.conf"
    printf '%s\ninclude $(dir $(lastword $(MAKEFILE_LIST)))devkit.mk\n%s\n' "$1" "$2" >"$dir/Makefile"
    git -C "$dir" init -q
    printf '%s\n' "$dir"
}

own='init:
	@echo the service first'

# The default goal is the service's, with the include before its first target and after it.
for where in before after; do
    if [ "$where" = before ]; then dir=$(service "" "$own" "$where"); else dir=$(service "$own" "" "$where"); fi
    said=$(make -s -C "$dir" 2>&1) || fail "include $where: a plain make failed: $said"
    [ "$said" = "the service first" ] || fail "include $where: a plain make ran something else: $said"
done

# A value set before the include is the one the targets use; without one, the fragment's.
dir=$(service 'PYTEST_WORKERS_MAX := 3' "$own" capped)
said=$(make -n -C "$dir" container-test 2>&1)
case $said in
*"DEVKIT_SIZE_WORKERS=3 scripts/container.sh make test"*) ;;
*) fail "PYTEST_WORKERS_MAX set by the service is not what container-test sizes to: $said" ;;
esac
dir=$(service "" "$own" default)
said=$(make -n -C "$dir" container-test 2>&1)
case $said in
*"DEVKIT_SIZE_WORKERS=6 scripts/container.sh make test"*) ;;
*) fail "without a PYTEST_WORKERS_MAX of the service, container-test is not sized to 6: $said" ;;
esac

# The fast stage, and the record of a full run that it reads.
said=$(make -n -C "$dir" test-fast FAST_BASE=HEAD PYTEST_WORKERS=2 2>&1)
case $said in
*"scripts/ci/fast_stage.py run --base HEAD -- -n 2"*) ;;
*) fail "test-fast does not run the fast stage with its base and workers: $said" ;;
esac
said=$(make -n -C "$dir" test-python 2>&1)
case $said in
*"fast_stage.py begin python"*"--junitxml=state/fast-stage/junit.xml"*"fast_stage.py record"*"fast_stage.py passed python"*) ;;
*) fail "test-python does not record its run for the fast stage: $said" ;;
esac

# From another directory, with -f: the include is found, and the keep container is named for this checkout.
said=$(cd "$work" && make -n -f "$dir/Makefile" container-keep 2>&1) || fail "make -f from elsewhere failed: $said"
case $said in
*"DEVKIT_CONTAINER_NAME=svc-keep"*) ;;
*) fail "make -f from elsewhere does not name the keep container for the service: $said" ;;
esac

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

if [ "$failures" -gt 0 ]; then
    echo "$failures check(s) failed" >&2
    exit 1
fi
echo "devkit.mk: all checks passed"
