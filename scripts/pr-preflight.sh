#!/bin/sh
# What this branch obliges you to do, read off the files it touches.
#
# AGENTS.md and the four directory files between them hold more rules than anybody recalls
# at the moment one applies. Most are conditional on what a change touches, which is a
# question a diff answers - so it is asked here rather than remembered. Run it before the
# pull request, and again after a rebase that pulled in more files.
#
#   scripts/pr-preflight.sh [base]     base defaults to origin/main
#
# It prints and exits 0 unless the last section could not look at everything: an unknown
# base, an origin it could not read, work on origin this checkout has not fetched, a branch
# git refused to compare, or a path with a newline in it. Nothing here is a gate: `make
# container-verify` is the gate, and a checklist that could fail a build would be worked
# around within a week. But that last section answers `none`, which is read as nobody else
# being in these files and so as leave to restructure them - so it is printed only when the
# scan looked at every branch, and anything less says what it could not see.

set -eu

base=${1:-origin/main}

# Every path below is repo-root-relative, and after `--` git reads a pathspec relative to
# the cwd - so from `scripts/`, `-- AGENTS.md` means `scripts/AGENTS.md` and matches
# nothing. The contention scan then printed "none" while the collision was real. Same
# question from the other side: `git ls-files --others` lists only what is under the cwd,
# so an untracked file elsewhere in the tree fell out of the rule list too.
toplevel=$(git rev-parse --show-toplevel 2>/dev/null) || {
    printf 'not inside a git repository\n' >&2
    exit 1
}
cd -- "$toplevel"

# The scan reads the refs this checkout happens to hold, and they go stale in hours here -
# so what origin actually holds is asked for. Read, not fetched: `git fetch` would answer
# the same question and rewrite this repository's refs to do it, and `--prune` would delete
# the only local pointer to a branch somebody had force-pushed over, with no reflog entry
# left to recover the tip from. A checklist has no business doing either. What this checkout
# has not fetched is reported instead, with the one command that fixes it.
remote_listing=''
remote_read=no
if remote_listing=$(git ls-remote --heads origin 2>/dev/null); then
    remote_read=yes
fi

if ! merge_base=$(git merge-base "$base" HEAD 2>/dev/null); then
    printf 'cannot find a merge base with %s\n' "$base" >&2
    exit 1
fi

# The paths `git <command> <arguments>` lists, one to a line. Asked for with -z, because the
# readable listing is not the path: git quotes and escapes a path outside printable ASCII -
# a byte above it, a `"`, a backslash, a tab - and the escaped spelling matches no rule
# below and no file as a pathspec. NUL-delimited, git hands over the bytes it has. A line
# cannot hold a newline, so one in a path becomes a \001 byte, which the scan below
# reports rather than turning into a pathspec that matches nothing.
#
# Through a file rather than a pipe, because a pipe answers with tr's status: a listing git
# could not give would read as an empty one, and the script would say "nothing changed".
# The exit leaves the command substitution the call is in, which fails the assignment, and
# set -e stops the script there.
soh=$(printf '\001')
listing=$(mktemp)
trap 'rm -f "$listing"' EXIT
paths() {
    _command=$1
    shift
    git "$_command" -z "$@" > "$listing" || exit 1
    tr '\n\0' '\001\n' < "$listing"
}

# --no-renames, because a rename is reported as its destination alone and the question here
# is who else is in the path this branch is moving away from. AGENTS.md wrote the scan for
# "a split, an extraction, a rename across a module", and with rename detection on, the one
# path that matters was never in the list to ask about.
changed=$(paths diff --name-only --no-renames "$merge_base" HEAD; paths diff --name-only --no-renames; paths diff --name-only --no-renames --staged; paths ls-files --others --exclude-standard)
changed=$(printf '%s\n' "$changed" | sort -u | sed '/^$/d')

# What this branch adds, as opposed to what it edits. The rules differ: a licence header
# is owed by a new file and by no other. Rename detection stays on here, so that a file
# this branch only moved is not asked for one.
added=$(paths diff --name-only --diff-filter=A "$merge_base" HEAD; paths diff --name-only --diff-filter=A --staged; paths ls-files --others --exclude-standard)
added=$(printf '%s\n' "$added" | sort -u | sed '/^$/d')

if [ -z "$changed" ]; then
    printf 'nothing changed against %s\n' "$base"
    exit 0
fi

touches() {
    printf '%s\n' "$changed" | grep -qE "$1"
}

adds() {
    printf '%s\n' "$added" | grep -qE "$1"
}

say() {
    printf '\n  %s\n' "$1"
    shift
    for _line in "$@"; do
        printf '      %s\n' "$_line"
    done
}

printf 'Against %s, this branch touches %s file(s).\n' "$base" "$(printf '%s\n' "$changed" | wc -l | tr -d ' ')"

# Both test layers, and the book that decides what the interface may look like. The
# interface is not only `assets/`: app/client/templates/ is the server-rendered half, and
# AGENTS.md's rule is about an interface change rather than about a directory.
if touches '^assets/|^app/(client|admin)/(templates|static)/'; then
    say 'the interface' \
        'Read the design book chapter for what you are touching, and load the' \
        'frontend-design skill. Both, before you touch it: docs/design-book.html.' \
        'A new token, hue, chip, icon meaning or type role needs an issue first AND a' \
        'change to the book in the same PR - CONTRIBUTING.md, Design changes.' \
        'A UI change needs vitest tests beside the code AND Playwright coverage in' \
        'e2e/tests/. One layer is an incomplete change.' \
        'Screenshots in the PR, captured from the spec: scripts/pr-screenshots.sh'
fi

# The async matrix, which is where this repository keeps finding defects. Read against the
# worktree rather than against HEAD: every other rule here fires on uncommitted work, and
# this one asking for a commit first made it silent exactly while the component was being
# written.
component_lines() {
    git diff "$merge_base" -- ':(literal)assets/src/js/components/' | sed -n 's/^+//p'
    # A component this branch has not committed yet is in no diff at all, so it is read
    # whole. Every line of a new file is a line the branch added.
    printf '%s\n' "$added" | grep -E '^assets/src/js/components/.*\.svelte$' | while read -r _f; do
        [ -f "$_f" ] && cat -- "$_f"
    done
}

if printf '%s\n' "$changed" | grep -qE '^assets/src/js/components/.*\.svelte$'; then
    if component_lines | grep -qE '(fetch\(|await )'; then
        say 'a component that fetches - answer these before the review does' \
            'A response arriving late, after a newer one, after the surface closes,' \
            'after an error, after a success: what is on screen, and what does it claim?' \
            'What does the page draw when its first read fails?' \
            'Does the control commit what the list is showing, or what the form now says?'
    fi
fi

if touches '^app/(api/routes|roster/api|directory/api)/'; then
    say 'app/api/routes/, app/roster/api/ and app/directory/api/ - endpoints' \
        'A mutating endpoint that schedules background work needs a test in' \
        'tests/api/test_background_tasks.py that drains the tasks and asserts the effect.' \
        'A 200 says nothing about the half that runs after the response.' \
        'Element ids: the public one is title-derived and unstable, the internal one is not.' \
        'See app/api/routes/AGENTS.md.'
fi

# What the reading is built from, which is far more than app/actions/. This is the reader
# half of the path list .github/workflows/minutes-corpus.yml gates on - the workflow also
# gates on its own file and on tests/, which change no reading - and the two have to stay in
# step: that workflow's own comment records twice (#548, #680) what a missing path costs, and
# pr-preflight.test.sh holds this list to every reader path the workflow hashes.
reader='^app/actions/|^app/parsers/|^app/models/agenda/|^schema/'
reader="$reader"'|^app/models/(appointee_accounts|committee_changes|minutes_corrections)\.py$'
reader="$reader"'|^app/models/(ballot|board_actions|recorded_vote|resolution_clauses|resolution_scope|resolution_source)\.py$'
reader="$reader"'|^app/models/data/(aliases|appointee-accounts|minutes-corrections)\.yaml$'
reader="$reader"'|^app/committee_info_file/(holdings|model|parser|sections)\.py$'
reader="$reader"'|^app/(aliases|hashing|indentation|numbering|optional|slugs|text_sections|utils|wrapping)\.py$'
reader="$reader"'|^app/roster/(names|podling_documents|podlings)\.py$'
reader="$reader"'|^app/serializers/(__init__|agenda_serializer|board_records|minutes_serializer)\.py$'
reader="$reader"'|^scripts/index-minutes\.py$'

if touches "$reader"; then
    say 'the minutes reader - the published record' \
        'CI reads the record with this branch and with its base, and fails on a difference' \
        'that no commit allows with a Reading-Allow: <part> trailer. Read it first:' \
        'make container-minutes-reading-base, then make container-minutes-reading.' \
        'Read app/actions/AGENTS.md and run the four checks it names.' \
        'The corpus job gates on the same reader paths: .github/workflows/minutes-corpus.yml'
fi

if touches '^e2e/'; then
    say 'e2e/ - the end-to-end harness' \
        'make e2e-typecheck. Running the suite says nothing about the types in it.' \
        '?roles= sticks to the shared roster, so every role can end up looking the same.' \
        'A reused DEVKIT_KEEP container serves the bundle from when it started - drop it' \
        'after any change under app/ or assets/. See e2e/README.md.'
fi

if touches '^app/(db/models|roster/tables|directory/tables|telemetry/models)\.py$'; then
    say 'the models of a database - a new table' \
        'Add a sequential Alembic migration to the chain of the database that holds it:' \
        'app/db/migrations/versions/, app/roster/migrations/versions/,' \
        'app/directory/migrations/versions/ or app/telemetry/migrations/versions/.' \
        'Add a table of BAT core, the roster or the directory to the admin data browser,' \
        'route /data, with the session of the database that holds it. BAT core'"'"'s tables go in' \
        'app/admin/routes.py; the roster names its own with browse() in app/roster/admin.py,' \
        'and the directory its own with browse() in app/directory/admin.py.'
fi

# What a user can now do is a claim the Documentation page makes, and it is the only
# account of the workflow anybody reads.
if touches '^app/(api/routes|roster/api|directory/api|client)/|^assets/src/js/components/'; then
    say 'a control moved, was renamed, or somebody can now do something new' \
        'The Documentation page changes in the same PR: app/md/documentation/.' \
        'Say who, not just what - the page is read by people checking whether a' \
        'control is theirs, and a route that refuses a role has to say so.' \
        'A new step in the process also changes the month timeline in overview.md.'
fi

if touches '^(pyproject\.toml|uv\.lock)$'; then
    say 'dependencies' \
        'uv.lock is the source of truth. Production installs it with uv sync --frozen.'
fi

# Asked of what the branch adds rather than of what it changes: the header is owed by a
# new file and by no other, and a block that printed on every Python branch would stop
# being read on the one where it applied.
if adds '\.py$'; then
    say 'new Python files' \
        'Apache 2.0 licence header, enforced by the insert-license hook.'
fi

# The rules that apply to every branch, and the ones that are easiest to skip.
say 'every branch' \
    'New files are invisible to the hooks until staged - git add them before make check,' \
    'or the first CI run is the first time they are linted.' \
    'Show every new assertion failing against the code as it was, and put what it' \
    'reported in the PR.' \
    'make container-quality-base, then make container-verify. Re-run the base after a rebase.' \
    'The ratchet is argued with, not lowered: a Quality-Allow: trailer in the commit that' \
    'makes the regression, never a smaller MAX_CYCLOMATIC.' \
    '/simplify before the push, then verify again - the pass below reads what was pushed,' \
    'so simplifying after it spends the pass on code you are about to rewrite. Only what' \
    'this branch added; if it touches a new file, run this scan again.' \
    'After the push and before the PR, a fresh subagent attacks the branch - never a fork.'

# Who else is in these files. Asked against each branch merge base rather than against
# main, because `git diff origin/main origin/<branch>` also reports every commit that
# branch is merely behind by.
#
# The file list becomes a pathspec, so it is split on newlines rather than on whitespace:
# a path with a space in it is one pathspec, and split on spaces it becomes two that match
# nothing - which makes the section answer `none`, the one answer it must never give
# wrongly. `set -f` so a `*` or `?` in a name is not expanded against the worktree on
# the way past, and `:(literal)` so git does not expand it either once it has one.
#
# The branch this checkout is on is excluded by its upstream, not by its own name: a local
# branch may be called something else, and on a detached HEAD `--abbrev-ref` answers
# `HEAD`. Either way the name was wrong and this branch reported a collision with itself.
here_branch=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null) ||
    here_branch=origin/$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)

saved_ifs=$IFS
IFS='
'
set -f
# shellcheck disable=SC2086  # split on newlines only, which is what IFS above says
set -- $changed
set +f
IFS=$saved_ifs

pathspecs=''
newline_path=no
for _p in "$@"; do
    # A newline in a path came through `paths` as a \001, and the pathspec made of it matches
    # nothing - so the scan must not answer "none" over it. A path holding a \001 of its own
    # is reported the same way, and matches as itself all the same.
    case $_p in
        *"$soh"*) newline_path=yes ;;
        *) : ;;
    esac
    pathspecs="$pathspecs:(literal)$_p
"
done
saved_ifs=$IFS
IFS='
'
set -f
# shellcheck disable=SC2086  # one pathspec per line, as built just above
set -- $pathspecs
set +f
IFS=$saved_ifs

printf '\n  branches that touch the same files\n'
found=no
unreadable=no
for ref in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin); do
    case $ref in
        origin | origin/HEAD | origin/main | "$here_branch") continue ;;
        *) : ;;
    esac
    # Your own pushed work, under whatever name it went up as. Excluding by upstream alone
    # left two ways to collide with yourself: a branch pushed as `mine:feat/other` has no
    # upstream at all, and in a fork layout `@{upstream}` names a remote that is not origin.
    # A ref HEAD already contains is one of those or is merged, and neither can conflict.
    if git merge-base --is-ancestor "$ref" HEAD 2>/dev/null; then
        continue
    fi
    # An unrelated history has no merge base, and dropping the ref there answered "not a
    # collision" about a branch that rewrites the same file. Name it instead - the reader
    # can compare it by hand, which is what this section is for. Not a failure: one orphan
    # branch on origin would otherwise make every run here exit non-zero for good.
    if ! ref_base=$(git merge-base "$base" "$ref" 2>/dev/null); then
        printf '      %s (no merge base with %s - compare it by hand)\n' "$ref" "$base"
        found=yes
        continue
    fi
    # Not `2>/dev/null`: git failing here - too many pathspecs for one argv, most likely -
    # printed nothing, which is indistinguishable from finding nothing.
    if ! overlap=$(git diff --name-only "$ref_base" "$ref" -- "$@" 2>&1); then
        printf '      %s (could not be compared: %s)\n' "$ref" "$(printf '%s' "$overlap" | head -1)"
        unreadable=yes
        continue
    fi
    if printf '%s' "$overlap" | grep -q .; then
        printf '      %s\n' "$ref"
        found=yes
    fi
done

# Branches this checkout has never fetched are branches the loop above could not look at,
# and saying "none" over them is the failure this whole section is about. Counted from what
# origin answered rather than from what a fetch wrote here.
if [ "$remote_read" = no ]; then
    printf '      (origin could not be read, so this is only what was already fetched)\n'
    unreadable=yes
else
    unseen=$(
        printf '%s\n' "$remote_listing" | while read -r _sha _ref; do
            [ -n "$_sha" ] || continue
            _name=${_ref#refs/heads/}
            _have=$(git rev-parse --verify --quiet "refs/remotes/origin/$_name") || _have=''
            [ "$_have" = "$_sha" ] || printf 'x\n'
        done | wc -l | tr -d ' '
    )
    if [ "$unseen" -gt 0 ]; then
        printf '      (%s branch(es) on origin are not in this checkout, so this list\n' "$unseen"
        printf '       cannot see them - git fetch, then run this again)\n'
        unreadable=yes
    fi
fi

if [ "$newline_path" = yes ]; then
    printf '      (a changed path holds a newline, which a list of paths one to a line\n'
    printf '       cannot hold - this list cannot see that file)\n'
    unreadable=yes
fi

if [ "$found" = no ] && [ "$unreadable" = no ]; then
    printf '      none\n'
else
    printf '\n      They say who to talk to, not whether you may merge.\n'
    printf '      git merge-tree --write-tree %s HEAD answers that, when you ask it.\n' "$base"
fi

printf '\n'

# A scan that could not look at every branch has not answered the question, and the whole
# point of the section is that "none" is trustworthy.
if [ "$unreadable" = yes ]; then
    printf 'the branch list above is incomplete - see the notes in it\n' >&2
    exit 1
fi
