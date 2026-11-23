#!/bin/sh
# What the kit lists in devkit.files, against what the kit holds. Kit only: a service has no
# devkit.files, and does not take this file.
#
# Nothing the kit holds is forgotten (it is listed, or it is declared the kit's own below), nothing
# listed is missing, and every copy a service takes says where to change it.

set -euf

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH='' cd -- "$here/.." && pwd)
cd "$root"

failures=0
fail() {
    echo "FAIL: $1" >&2
    failures=$((failures + 1))
}

# What is the kit's own and is not taken by a service: the files named here, and every path that matches
# one of the patterns after them. The tests are the kit's CI's, and a service has no use for a copy (see the
# README); docs/ records why the kit is the way it is.
kit_only='.asf.yaml .gitignore .python-version .tool-versions Makefile pyproject.toml uv.lock .github/dependabot.yml .github/workflows/test.yml LICENSE README.md AGENTS.md CLAUDE.md devkit.conf devkit.files'
kit_only_patterns='*.test.sh tests/* docs/*'
# What cannot carry the line that says where to change it: JSON and a license template have no comment.
no_header='.claude/settings.json scripts/ci/LICENSE-template.txt'
marker='Comes from apache/tooling-devkit (devkit.files): change it there, not in a copy.'

# Whether the path $1 matches one of the glob patterns in $2. Globbing is off (set -f), so the patterns
# stay words, and `case` does the matching.
matches_a_pattern() {
    for _pattern in $2; do
        # shellcheck disable=SC2254 # the pattern is the point
        case $1 in $_pattern) return 0 ;; *) : ;; esac
    done
    return 1
}

in_list() {
    for _item in $2; do
        [ "$_item" = "$1" ] && return 0
    done
    return 1
}

listed=$(sed -e '/^#/d' -e '/^[[:space:]]*$/d' devkit.files)
sources=$(printf '%s\n' "$listed" | awk '{print $1}')
destinations=$(printf '%s\n' "$listed" | awk '{print ($2 == "" ? $1 : $2)}')

# every path listed is a file the kit holds, once
for path in $sources; do
    [ -f "$path" ] || fail "devkit.files lists $path, which the kit does not have"
done
[ -z "$(printf '%s\n' "$sources" | sort | uniq -d)" ] || fail "devkit.files lists a source twice"
[ -z "$(printf '%s\n' "$destinations" | sort | uniq -d)" ] || fail "devkit.files lists a destination twice"

# every file the kit holds is listed, or the kit's own
for path in $(git ls-files); do
    if in_list "$path" "$kit_only" || matches_a_pattern "$path" "$kit_only_patterns"; then
        printf '%s\n' "$sources" | grep -q -x -F -- "$path" && fail "$path is the kit's own, and is listed"
        continue
    fi
    printf '%s\n' "$sources" | grep -q -x -F -- "$path" || fail "$path is neither in devkit.files nor the kit's own (this file)"
done

# every copy says where to change it, near the top
for path in $sources; do
    [ -f "$path" ] || continue
    if in_list "$path" "$no_header"; then
        continue
    fi
    head -n 40 "$path" | grep -q -F -- "$marker" || fail "$path does not say where to change it: no '$marker'"
done

if [ "$failures" -ne 0 ]; then
    echo "$failures devkit.files check(s) failed" >&2
    exit 1
fi

echo "devkit.files: every file is accounted for"
