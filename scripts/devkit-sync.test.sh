#!/bin/sh
# What devkit-sync.sh copies, what it leaves alone, and what its check says.
#
# The kit here is a repository made for the run, and DEVKIT_SOURCE names it, so nothing is fetched from
# the network. A repository of its own holds the copy of the script that is under test, as a service
# would.

set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

failures=0
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

fail() {
    echo "FAIL: $1" >&2
    [ -z "${output:-}" ] || printf '  output was:\n%s\n' "$output" | sed 's/^/    /' >&2
    failures=$((failures + 1))
}

kit="$work/kit"
svc="$work/svc"
git init -q "$kit"
commit_kit() {
    git -C "$kit" add -A
    git -C "$kit" -c user.name=t -c user.email=t@example.org commit -q -m "$1"
    git -C "$kit" rev-parse HEAD
}

# --- the kit, at its first commit ----------------------------------------------------------------
mkdir -p "$kit/scripts" "$kit/workflows" "$kit/.claude"
printf '# the files\n\nscripts/a.sh\nscripts/b.sh\nworkflows/w.yml .github/workflows/w.yml\n.claude/settings.json\n' \
    > "$kit/devkit.files"
printf '#!/bin/sh\necho a1\n' > "$kit/scripts/a.sh"
chmod +x "$kit/scripts/a.sh"
printf 'echo b1\n' > "$kit/scripts/b.sh"
printf 'name: w1\n' > "$kit/workflows/w.yml"
printf '{"one": 1}\n' > "$kit/.claude/settings.json"
printf 'kit only\n' > "$kit/README.md"
c1=$(commit_kit one)

# --- a service, with a copy of the script and its own devkit.conf ------------------------------------
mkdir -p "$svc/scripts"
cp "$here/devkit-sync.sh" "$svc/scripts/devkit-sync.sh"
printf 'DEVKIT_SERVICE=svc\nDEVKIT_REPOSITORY=apache/tooling-svc\n' > "$svc/devkit.conf"
mine="$(cat "$svc/devkit.conf")"

status=0
output=''
run() {
    status=0
    output=$(cd "$svc" && DEVKIT_SOURCE="$kit" "$@" 2>&1) || status=$?
}
sync_to() { run sh scripts/devkit-sync.sh "$1"; }
check() { run env DEVKIT_TODAY="${1:-2026-11-21}" sh scripts/devkit-sync.sh --check; }
says() { printf '%s\n' "$output" | grep -qF -- "$1"; }

# a first sync: the listed files, at the destination the kit gives, with the mode the kit gives,
# and the commit in devkit.lock; what the kit does not list is not copied
sync_to "$c1"
[ "$status" -eq 0 ] || fail "the first sync runs"
[ "$(cat "$svc/scripts/a.sh")" = "$(printf '#!/bin/sh\necho a1')" ] || fail "a listed file is copied"
[ -x "$svc/scripts/a.sh" ] || fail "and keeps the mode the kit gives it"
[ "$(cat "$svc/.github/workflows/w.yml")" = 'name: w1' ] || fail "a file with a destination goes there"
[ -f "$svc/workflows/w.yml" ] && fail "and not where the kit keeps it"
[ -f "$svc/README.md" ] && fail "a file the kit does not list is not copied"
[ "$(sed -n 's/^commit //p' "$svc/devkit.lock")" = "$c1" ] || fail "devkit.lock holds the commit"
[ "$(cat "$svc/devkit.conf")" = "$mine" ] || fail "devkit.conf is the service's own, and stays"
says "4 added" || fail "the sync says what it added"
check
[ "$status" -eq 0 ] || fail "the check passes right after a sync"
says "4 file(s) are as the kit has them" || fail "and says how many it looked at"

# a ref that is a branch name or HEAD works as well as a commit
sync_to HEAD
[ "$status" -eq 0 ] && says "0 added, 0 changed, 0 removed, 4 the same" || fail "a sync with nothing new changes nothing"

# --- drift ------------------------------------------------------------------------------------------
chmod -x "$svc/scripts/a.sh"
check
[ "$status" -ne 0 ] && says "drift: scripts/a.sh" || fail "a copy that lost its executable bit is drift"
chmod +x "$svc/scripts/a.sh"
printf 'echo edited\n' >> "$svc/scripts/b.sh"
check
[ "$status" -ne 0 ] || fail "an edited copy fails the check"
says "drift: scripts/b.sh" || fail "and the check names it"
says "1 problem(s) in 4 file(s)" || fail "and counts it"
printf 'echo b1\n' > "$svc/scripts/b.sh"
rm "$svc/.github/workflows/w.yml"
check
[ "$status" -ne 0 ] && says "missing: .github/workflows/w.yml" || fail "a copy that is gone is missing"
sync_to "$c1"
[ -f "$svc/.github/workflows/w.yml" ] || fail "the sync brings back a file that is gone"
check
[ "$status" -eq 0 ] || fail "and the check passes again"

# a sync takes the kit's version over a local edit: that is the drift going away
printf 'echo edited\n' >> "$svc/scripts/b.sh"
sync_to "$c1"
says "changed: scripts/b.sh" || fail "the sync says it replaced an edited copy"
check
[ "$status" -eq 0 ] || fail "and the copy is the kit's again"

# --- a file the service keeps as its own ------------------------------------------------------------
printf 'DEVKIT_SERVICE=svc\nDEVKIT_REPOSITORY=apache/tooling-svc\nDEVKIT_SKIP=scripts/b.sh .claude/settings.json\n' > "$svc/devkit.conf"
printf 'mine\n' > "$svc/scripts/b.sh"
printf '{"local": true}\n' > "$svc/.claude/settings.json"
sync_to "$c1"
[ "$(cat "$svc/scripts/b.sh")" = mine ] || fail "a file in DEVKIT_SKIP is not overwritten"
check
[ "$status" -eq 0 ] && says "2 file(s) are as the kit has them" || fail "and the check leaves it out"
printf 'DEVKIT_SERVICE=svc\nDEVKIT_REPOSITORY=apache/tooling-svc\n' > "$svc/devkit.conf"
printf 'echo b1\n' > "$svc/scripts/b.sh"
rm -f "$svc/.claude/settings.json"
sync_to "$c1"

# --- a kit that has moved on: a file changed, one dropped, one added ---------------------------------
printf '#!/bin/sh\necho a2\n' > "$kit/scripts/a.sh"
git -C "$kit" rm -q scripts/b.sh
printf 'echo c2\n' > "$kit/scripts/c.sh"
printf '# the files\n\nscripts/a.sh\nscripts/c.sh\nworkflows/w.yml .github/workflows/w.yml\n.claude/settings.json\n' \
    > "$kit/devkit.files"
c2=$(commit_kit two)
check
[ "$status" -eq 0 ] || fail "a kit that has moved on is not drift: the check reads the commit in devkit.lock"
sync_to "$c2"
[ "$status" -eq 0 ] || fail "the sync to the new commit runs"
[ "$(sed -n '2p' "$svc/scripts/a.sh")" = 'echo a2' ] || fail "a changed file is changed"
[ -f "$svc/scripts/c.sh" ] || fail "a file the kit added is added"
[ -f "$svc/scripts/b.sh" ] && fail "a file the kit dropped is removed"
says "removed: scripts/b.sh" || fail "and the sync says so"
[ "$(sed -n 's/^commit //p' "$svc/devkit.lock")" = "$c2" ] || fail "devkit.lock moves to the new commit"
printf 'kept\n' > "$svc/scripts/mine.sh"
sync_to "$c2"
[ -f "$svc/scripts/mine.sh" ] || fail "a file of the service that the kit never listed stays"

# --- overrides --------------------------------------------------------------------------------------
printf 'echo local\n' >> "$svc/scripts/c.sh"
printf '# why\noverride scripts/c.sh tooling-svc#7 until 2026-12-31\n' >> "$svc/devkit.lock"
check 2026-11-21
[ "$status" -eq 0 ] || fail "an overridden file may differ until its day"
says "override: scripts/c.sh (tooling-svc#7) until 2026-12-31" || fail "and the check prints the override every time"
check 2026-12-31
[ "$status" -eq 0 ] || fail "the override holds on its last day"
check 2027-01-01
[ "$status" -ne 0 ] && says "the override of scripts/c.sh ended on 2026-12-31" || fail "an override past its day fails the check"
sync_to "$c2"
says "kept (override): scripts/c.sh" || fail "the sync says it left an overridden file"
grep -q 'local' "$svc/scripts/c.sh" || fail "and leaves it as it is"
grep -q '^override scripts/c.sh tooling-svc#7 until 2026-12-31$' "$svc/devkit.lock" || fail "the override stays in devkit.lock"
grep -q '^# why$' "$svc/devkit.lock" || fail "and so does the rest of the file"
printf 'override scripts/c.sh\n' >> "$svc/devkit.lock"
check
[ "$status" -ne 0 ] && says "an override is 'override <path> <issue> until <YYYY-MM-DD>'" || fail "a malformed override is refused"
printf '# why\noverride scripts/c.sh tooling-svc#7 until 2026-12-31x\n' > "$svc/devkit.lock.new"
printf 'commit %s\n' "$c2" | cat - "$svc/devkit.lock.new" > "$svc/devkit.lock"
rm "$svc/devkit.lock.new"
check
[ "$status" -ne 0 ] && says "the day an override ends is YYYY-MM-DD" || fail "an end that is not a day is refused"
printf 'commit %s\n' "$c2" > "$svc/devkit.lock"
printf 'echo c2\n' > "$svc/scripts/c.sh"

# --- what is refused ---------------------------------------------------------------------------------
rm "$svc/devkit.lock"
check
[ "$status" -ne 0 ] && says "there is no devkit.lock" || fail "no devkit.lock fails the check"
printf 'commit abc123\n' > "$svc/devkit.lock"
check
[ "$status" -ne 0 ] && says "no commit line of 40 hex digits" || fail "a commit that is not 40 hex digits is refused"
printf 'commit %s\n' "$c2" > "$svc/devkit.lock"
for ref in '' '-x' '--check=x' 'a b' 'x;y'; do
    sync_to "$ref"
    [ "$status" -ne 0 ] || fail "the ref '$ref' is refused"
done
sync_to no-such-ref
[ "$status" -ne 0 ] && says "cannot fetch 'no-such-ref'" || fail "a ref the kit does not have fails, and says so"
[ "$(sed -n 's/^commit //p' "$svc/devkit.lock")" = "$c2" ] || fail "and devkit.lock is as it was"
run sh scripts/devkit-sync.sh a b
[ "$status" -eq 2 ] || fail "two arguments are a usage error"
mv "$svc/devkit.conf" "$svc/devkit.conf.off"
sync_to "$c2"
[ "$status" -ne 0 ] && says "there is no devkit.conf" || fail "a repository without devkit.conf is refused"
mv "$svc/devkit.conf.off" "$svc/devkit.conf"

# a kit that lists a path the sync must not write: nothing is copied, and the reason is the path. The
# kit holds a file there where it can, so that a refusal is not a missing source.
printf 'the kit\n' > "$kit/devkit.conf"
printf 'the kit\n' > "$kit/devkit.lock"
mkdir -p "$kit/.git-copy"
for bad in '/etc/passwd' '../outside' 'scripts/../../outside' 'devkit.conf' 'devkit.lock' '.claude/settings.additions.json' '.git/config' 'odd$name'; do
    printf '%s\n' "$bad" > "$kit/devkit.files"
    bad_commit=$(commit_kit "lists $bad")
    sync_to "$bad_commit"
    [ "$status" -ne 0 ] || fail "a kit that lists '$bad' is refused"
    case $bad in
        'odd$name') says "a path with an odd character: $bad" || fail "'$bad': the reason is the character" ;;
        *) says "lists a path the sync does not write: $bad" || fail "'$bad': the reason is the path" ;;
    esac
done
printf 'a b c\n' > "$kit/devkit.files"
sync_to "$(commit_kit 'lists three words')"
[ "$status" -ne 0 ] && says "more than a source and a destination" || fail "a line of three words is refused"
[ -e "$work/outside" ] && fail "nothing was written outside the repository"
[ "$mine" = "$(cat "$svc/devkit.conf")" ] || fail "devkit.conf is as it was after a kit that listed it"
[ "$(sed -n 's/^commit //p' "$svc/devkit.lock")" = "$c2" ] || fail "devkit.lock is as it was after a kit that listed it"

# --- .claude/settings.json: the base of the kit, and what a repository adds ----------------------------------
# The one file that is not a byte copy. A second kit and a second service, so that the first run is untouched.

kit="$work/kit2"
svc="$work/svc2"
git init -q "$kit"
mkdir -p "$kit/.claude" "$svc/scripts" "$svc/.claude"
cat > "$kit/.claude/settings.json" << 'JSON'
{
  "permissions": {
    "allow": ["Bash(make a:*)", "Bash(make b:*)"],
    "deny": ["Read(./.env)"]
  },
  "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard"}]}]}
}
JSON
printf '.claude/settings.json\n' > "$kit/devkit.files"
s1=$(commit_kit settings)
cp "$here/devkit-sync.sh" "$svc/scripts/devkit-sync.sh"
printf 'DEVKIT_SERVICE=svc2\nDEVKIT_REPOSITORY=apache/tooling-svc2\n' > "$svc/devkit.conf"
settings="$svc/.claude/settings.json"
additions="$svc/.claude/settings.additions.json"

# a field of the merged file, as a line of JSON, for what is asserted below
field() { python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps(eval(sys.argv[2]), sort_keys=True))' "$settings" "$1"; }

# no additions: a byte copy, as every other file is
sync_to "$s1"
[ "$status" -eq 0 ] || fail "a sync of settings with no additions runs"
[ "$(cat "$settings")" = "$(cat "$kit/.claude/settings.json")" ] || fail "settings with no additions are a byte copy of the kit's"
check
[ "$status" -eq 0 ] || fail "and the check passes"

# additions: appended after the kit's entries, with no duplicates, and nothing else of the kit's changes
cat > "$additions" << 'JSON'
{"permissions": {"allow": ["Bash(make c:*)", "Bash(make a:*)", "Bash(make c:*)"], "deny": ["Read(./secret.yaml)"]}}
JSON
sync_to "$s1"
[ "$status" -eq 0 ] || fail "a sync with additions runs"
[ "$(field 'd["permissions"]["allow"]')" = '["Bash(make a:*)", "Bash(make b:*)", "Bash(make c:*)"]' ] ||
    fail "the additions to allow follow the kit's entries, once each: $(field 'd["permissions"]["allow"]')"
[ "$(field 'd["permissions"]["deny"]')" = '["Read(./.env)", "Read(./secret.yaml)"]' ] ||
    fail "the additions to deny follow the kit's: $(field 'd["permissions"]["deny"]')"
[ "$(field 'd["hooks"]')" = "$(python3 -I -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["hooks"], sort_keys=True))' "$kit/.claude/settings.json")" ] ||
    fail "the hook that registers the guard is the kit's, untouched"
[ -f "$additions" ] && grep -q 'secret.yaml' "$additions" || fail "the additions file of the repository is left as it was"
check
[ "$status" -eq 0 ] || fail "the check passes right after a sync with additions"

# the file is drift from the base and the additions alike
printf '\n' >> "$settings"
check
[ "$status" -ne 0 ] && says 'drift: .claude/settings.json differs from the kit at' && says 'with .claude/settings.additions.json' ||
    fail "an edit of the merged file was not drift, with the additions named"
sync_to "$s1"
check
[ "$status" -eq 0 ] || fail "a sync takes the merged file back to what the base and the additions make"
cat > "$additions" << 'JSON'
{"permissions": {"allow": ["Bash(make d:*)"]}}
JSON
check
[ "$status" -ne 0 ] && says 'drift: .claude/settings.json' || fail "a change to the additions is drift until a sync"
sync_to "$s1"
[ "$(field 'd["permissions"]["allow"]')" = '["Bash(make a:*)", "Bash(make b:*)", "Bash(make d:*)"]' ] ||
    fail "the additions of today are the ones in the file"

# what a repository may not add is refused with every reason, and nothing is copied
before=$(cat "$settings")
refused_additions() {
    printf '%s\n' "$1" > "$additions"
    sync_to "$s1"
    if [ "$status" -eq 0 ]; then
        fail "additions of $2 were accepted"
    elif ! says "$3"; then
        fail "additions of $2: the reason was not said ($3)"
    fi
    [ "$(cat "$settings")" = "$before" ] || fail "additions of $2 changed the settings anyway"
}
refused_additions '{"hooks": {}}' 'a hook' 'hooks is not something a repository adds'
refused_additions '{"permissions": {"hooks": []}}' 'a key of permissions it may not' 'permissions.hooks is not something a repository adds'
refused_additions '{"permissions": {"allow": "Bash(x)"}}' 'a string for a list' 'permissions.allow is a list of non-empty strings'
refused_additions '{"permissions": {"deny": ["ok", ""]}}' 'an empty entry' 'permissions.deny is a list of non-empty strings'
refused_additions '{"permissions": []}' 'permissions that is no object' 'permissions is an object'
refused_additions '[1]' 'a list' 'the file is a JSON object'
refused_additions 'not json' 'what is not JSON' 'the file cannot be read'
printf '%s\n' '{"hooks": 1, "permissions": {"deny": "x", "other": []}}' > "$additions"
sync_to "$s1"
[ "$status" -ne 0 ] && says 'hooks is not' && says 'permissions.other is not' && says 'permissions.deny is a list' ||
    fail "not every reason was given at once"

# the additions of a repository that keeps the file as its own are not read, and without python they cannot be
printf '%s\n' '{"hooks": 1}' > "$additions"
printf 'DEVKIT_SERVICE=svc2\nDEVKIT_REPOSITORY=apache/tooling-svc2\nDEVKIT_SKIP=.claude/settings.json\n' > "$svc/devkit.conf"
sync_to "$s1"
[ "$status" -eq 0 ] || fail "additions were read for a file the repository keeps as its own"
printf 'DEVKIT_SERVICE=svc2\nDEVKIT_REPOSITORY=apache/tooling-svc2\n' > "$svc/devkit.conf"
printf '%s\n' '{"permissions": {"allow": ["Bash(make e:*)"]}}' > "$additions"
DEVKIT_SYNC_PYTHON=/no/such/python3
export DEVKIT_SYNC_PYTHON
sync_to "$s1"
unset DEVKIT_SYNC_PYTHON
[ "$status" -ne 0 ] && says 'needs python3' || fail "additions with no python were not refused, and said"

# without an additions file, a repository needs no python at all
rm -f "$additions"
DEVKIT_SYNC_PYTHON=/no/such/python3
export DEVKIT_SYNC_PYTHON
sync_to "$s1"
unset DEVKIT_SYNC_PYTHON
[ "$status" -eq 0 ] || fail "a repository without additions needed python"
[ "$(cat "$settings")" = "$(cat "$kit/.claude/settings.json")" ] || fail "and settings are the kit's again with the additions gone"

# --- a file the kit moves to another source, and one whose executable bit changes -------------------------
kit="$work/kit3"
svc="$work/svc3"
git init -q "$kit"
mkdir -p "$kit/old" "$kit/new" "$svc/scripts"
printf 'old/t.sh scripts/t.sh\n' > "$kit/devkit.files"
printf '#!/bin/sh\necho old\n' > "$kit/old/t.sh"
chmod +x "$kit/old/t.sh"
m1=$(commit_kit one)
cp "$here/devkit-sync.sh" "$svc/scripts/devkit-sync.sh"
printf 'DEVKIT_SERVICE=svc3\nDEVKIT_REPOSITORY=apache/tooling-svc3\n' > "$svc/devkit.conf"
sync_to "$m1"
[ -x "$svc/scripts/t.sh" ] || fail "the first copy is executable, as the kit has it"
git -C "$kit" rm -q -r old
printf 'new/t.sh scripts/t.sh\n' > "$kit/devkit.files"
printf '#!/bin/sh\necho new\n' > "$kit/new/t.sh"
m2=$(commit_kit moved)
sync_to "$m2"
[ "$status" -eq 0 ] || fail "a sync of a file the kit moved runs"
[ -f "$svc/scripts/t.sh" ] || fail "a file the kit moved to another source is not removed: its destination is still the kit's"
[ "$(sed -n 2p "$svc/scripts/t.sh")" = "echo new" ] || fail "and it has the new content"
[ ! -x "$svc/scripts/t.sh" ] || fail "and the mode of the new copy, not the mode of the one it replaced"
check
[ "$status" -eq 0 ] || fail "the check passes right after: a mode the sync did not copy would be drift"

if [ "$failures" -ne 0 ]; then
    echo "$failures devkit-sync case(s) failed" >&2
    exit 1
fi

echo "devkit-sync.sh: every case holds"
