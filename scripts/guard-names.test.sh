#!/bin/sh
# The names a make wrapper may be given, held to what the kit's scripts read.
#
# The guard refuses everything on a make line but its target and the NAME=value pairs it lists, and says in its
# own comment that the list is "the names the scripts read, and no others". Nothing held it to that: a script
# that starts reading a new variable would be unlisted without anybody having decided so. This does. Every
# DEVKIT_ name a script of the kit uses is either allowed on a make line or named below, with the reason it is
# not, and a name in either place that no script uses is a stale entry.
#
# See docs/design.md, 11.

set -euf

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH='' cd -- "$here/.." && pwd)
cd "$root"

failures=0
fail() {
    echo "FAIL: $1" >&2
    failures=$((failures + 1))
}

# A setting a person changes for one run of a wrapper, which is how the guard allows it on a make line -
# a plain value only - is everything it lists. These are the names that are not, and why.
#
# The guard's own switches: given on a command line they would turn it off.
#   DEVKIT_ISOLATED
# A program or a place the script runs or fetches from: a value there is code, not a setting.
#   DEVKIT_WORKTREE_DONE (the command worktree-sweep runs) and DEVKIT_SOURCE (where devkit-sync fetches the kit)
# Given to a script directly, which is not a make wrapper.
#   DEVKIT_SWEEP_IDLE_HOURS (worktree-sweep)
# Read from devkit.conf or worked out from it by the scripts, and not an environment setting.
#   DEVKIT_SERVICE, DEVKIT_REPOSITORY, DEVKIT_RUN_DIR, DEVKIT_SKIP
# Hooks that exist for the kit's own tests.
#   DEVKIT_MEMINFO, DEVKIT_NPROC, DEVKIT_GATE_POLL, DEVKIT_TODAY, DEVKIT_SYNC_PYTHON
# Set by a script or by CI for what it starts, and not by a person.
#   DEVKIT_APT_CACHE (the apt-install action), DEVKIT_BEHAVIOUR_OUT, DEVKIT_BEHAVIOUR_EXECUTED,
#   DEVKIT_BEHAVIOUR_SELECT (behaviour.py, for its child run)
# Checked on its own, as a program name that is podman or docker.
#   DEVKIT_RUNTIME
not_on_a_make_line='DEVKIT_ISOLATED DEVKIT_WORKTREE_DONE DEVKIT_SOURCE DEVKIT_SWEEP_IDLE_HOURS DEVKIT_SERVICE DEVKIT_REPOSITORY DEVKIT_RUN_DIR DEVKIT_SKIP DEVKIT_MEMINFO DEVKIT_NPROC DEVKIT_GATE_POLL DEVKIT_TODAY DEVKIT_SYNC_PYTHON DEVKIT_APT_CACHE DEVKIT_BEHAVIOUR_OUT DEVKIT_BEHAVIOUR_EXECUTED DEVKIT_BEHAVIOUR_SELECT DEVKIT_RUNTIME'

guard=.claude/hooks/guard-bash.sh

# What the guard lists: the names after its comment, up to the end of the pattern. The make variables of the
# targets (KEEP_PORT, QUALITY_REF and the like) are in the same pattern and are not DEVKIT_ names.
listed=$(sed -n '/the DEVKIT_\* names the scripts read/{n;:a;p;/)$/q;n;ba;}' "$guard" | grep -oE '[A-Z][A-Z0-9_]+' || true)
allowed=$(printf '%s\n' "$listed" | grep '^DEVKIT_' | sort -u)
make_variables=$(printf '%s\n' "$listed" | grep -v '^DEVKIT_' | sort -u)

# What the scripts of the kit use: not its tests, and not the guard, which names them to refuse.
used=$(git ls-files scripts .github .claude/commands Makefile devkit.mk |
    grep -v -E '\.test\.sh$' |
    while IFS= read -r file; do grep -hoE 'DEVKIT_[A-Z0-9_]+' "$file" || true; done | sort -u)

[ -n "$allowed" ] || fail "no DEVKIT_ names were found in the guard's list: the comment it is found by has moved"
[ -n "$used" ] || fail "no DEVKIT_ names were found in the scripts"

in_words() {
    for _w in $2; do
        [ "$_w" = "$1" ] && return 0
    done
    return 1
}

for name in $used; do
    if printf '%s\n' "$allowed" | grep -qxF -- "$name"; then
        in_words "$name" "$not_on_a_make_line" && fail "$name is allowed on a make line, and is declared as not"
    elif ! in_words "$name" "$not_on_a_make_line"; then
        fail "$name is read by a script and is neither allowed on a make line nor declared as not: decide, in the guard's list or in this file"
    fi
done
for name in $allowed; do
    printf '%s\n' "$used" | grep -qxF -- "$name" || fail "$name is allowed on a make line, and no script of the kit uses it"
done
for name in $not_on_a_make_line; do
    printf '%s\n' "$used" | grep -qxF -- "$name" || fail "$name is declared as not for a make line, and no script of the kit uses it"
done

# The guard does what the lists say.
DEVKIT_GUARD_FORCE=1
export DEVKIT_GUARD_FORCE
unset DEVKIT_ISOLATED

as_json_string() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# whether the guard allows one command
status_of() {
    printf '{"session_id":"t","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"%s","description":"x"}}' \
        "$(as_json_string "$1")" | sh "$guard" > /dev/null 2>&1
}

for name in $allowed $make_variables; do
    status_of "make container-test $name=1" || fail "the guard refuses the allowed name $name with a plain value"
done
for name in $not_on_a_make_line; do
    case $name in
        DEVKIT_RUNTIME) continue ;;
        *) : ;;
    esac
    if status_of "make container-test $name=1"; then
        fail "the guard allows $name on a make line, and it is declared as not"
    fi
done
# and a plain value is the only kind: a name that is allowed is held to it. These are the characters only that
# check refuses - another part of the guard reads a quote, a `$`, a `;` or a backtick first, and would refuse
# them whether or not it held - and `!` is the one the pattern it replaced let through.
for name in $allowed; do
    for value in 'x!y' 'a*b' 'a%b' 'a@b'; do
        if status_of "make container-test $name=$value"; then
            fail "the guard allows $name=$value: a value that is more than a plain value"
        fi
    done
done

if [ "$failures" -ne 0 ]; then
    echo "$failures name(s) of a make line are not accounted for" >&2
    exit 1
fi

echo "guard names: every DEVKIT_ name of the scripts is allowed on a make line or declared as not"
