#!/bin/sh
# How container.sh sizes a run of the whole suite, and the gate slots that keep concurrent runs from
# asking the machine for more memory than it has (scripts/container-size.sh).
#
# What matters most is what goes wrong quietly. A run sized too large is OOM-killed, or kills a
# neighbour; a slot that is not let go makes every later run wait for ever; a lock that is not taken
# lets two runs start on a machine with room for one. Each of those is a test here.
#
# The runtime is a stub on PATH, as in container.test.sh, which records the argv it is given and
# holds the run open until told to let go - so that a run holds its slot for as long as a test needs
# it to. The machine is a meminfo file and a core count (DEVKIT_MEMINFO, DEVKIT_NPROC), and the slots are in
# the git directory of a copy of the scripts, so nobody's real slots are touched.
#
# Run by prek (see .pre-commit-config.yaml), and so by `make check`.

set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
# the PATH this test was given, for a run that puts a stand-in of its own in front of it
given_path=$PATH

failures=0
fail() {
    echo "FAIL: $1" >&2
    failures=$((failures + 1))
}

work=$(mktemp -d)
cleanup() {
    # a run left holding would otherwise outlive the test
    touch "$work/stop"
    for f in "$work"/*.pid; do
        [ -f "$f" ] && kill -KILL "$(cat "$f")" 2>/dev/null || true
    done
    rm -rf "$work"
}
trap cleanup EXIT

# --- the arithmetic, on constants chosen to make it legible ----------------------------------

(
    # shellcheck source=scripts/container-size.sh
    . "$here/container-size.sh"
    GATE_BASE_MIB=1000
    GATE_WORKER_MIB=500
    GATE_SPARE_MIB=1024
    GATE_SLOT_WORKERS=6
    bad=0
    expect() {
        [ "$2" = "$3" ] || { echo "FAIL: $1: expected '$3', got '$2'" >&2; bad=$((bad + 1)); }
    }
    refused() {
        (gate_mib_of "$2") > /dev/null 2>&1 && { echo "FAIL: $1" >&2; bad=$((bad + 1)); }
        return 0
    }

    expect "a run's memory is the base and a share for each worker" "$(gate_memory 3)" 2500
    expect "a budget holds as many workers as fit whole" "$(gate_fit 2499 16 6)" 2
    expect "and one that fits exactly" "$(gate_fit 2500 16 6)" 3
    expect "the first worker fits exactly" "$(gate_fit 1500 16 6)" 1
    expect "a budget a MiB short of one worker holds none" "$(gate_fit 1499 16 6)" 0
    expect "a budget far below the base holds none, though sh truncates towards zero" "$(gate_fit 499 16 6)" 0
    expect "no more workers than the command can use" "$(gate_fit 100000 16 6)" 6
    expect "no more workers than there are cores" "$(gate_fit 100000 2 6)" 2

    # a slot is sized for six workers, 4000 MiB here, after the spare
    expect "as many slots as six-worker runs fit, after the spare" "$(gate_slots $((9024 * 1024)))" 2
    expect "and the spare is taken first" "$(gate_slots $((9000 * 1024)))" 1
    expect "a machine too small for one still has one" "$(gate_slots $((2000 * 1024)))" 1

    expect "a count is read as decimal" "$(gate_number X 08)" 8
    expect "and zero as zero" "$(gate_number X 000)" 0
    (gate_number X 3x) > /dev/null 2>&1 && { echo "FAIL: a count that is not one is refused" >&2; bad=$((bad + 1)); }

    expect "DEVKIT_MEMORY in g" "$(gate_mib_of 10g)" 10240
    expect "in m" "$(gate_mib_of 512m)" 512
    expect "in k" "$(gate_mib_of 2097152k)" 2048
    expect "in bytes" "$(gate_mib_of 1073741824)" 1024
    expect "in bytes, said so" "$(gate_mib_of 1073741824b)" 1024
    expect "as GiB, the way podman also takes it" "$(gate_mib_of 6GiB)" 6144
    expect "as gb" "$(gate_mib_of 6gb)" 6144
    expect "as gi" "$(gate_mib_of 6gi)" 6144
    expect "as mb" "$(gate_mib_of 512mb)" 512
    expect "as mib" "$(gate_mib_of 512MiB)" 512
    expect "as mi" "$(gate_mib_of 512Mi)" 512
    expect "as kb" "$(gate_mib_of 2097152kb)" 2048
    expect "as kib" "$(gate_mib_of 2097152KiB)" 2048
    expect "as ki" "$(gate_mib_of 2097152ki)" 2048
    expect "in capitals" "$(gate_mib_of 6G)" 6144
    refused "a word is refused" lots
    refused "a fraction is refused, which podman would take and this cannot read" 6.5g
    refused "a unit this does not read is refused" 1t
    refused "a unit in the middle is refused" 1g5
    refused "a number too long for the arithmetic is refused" 99999999999999g
    # 2^64 + 2^30 bytes: read modulo 2^64, as some shells would, it is 1 GiB
    refused "and one that the arithmetic would wrap into a size is refused too" 18446744074783293440b
    refused "more than a TiB is refused" 2048g
    refused "less than a MiB is refused" 100k
    exit "$bad"
) || failures=$((failures + $?))

# --- a copy of the scripts, in a repository of its own ---------------------------------------

fake="$work/repo"
mkdir -p "$fake/scripts" "$work/bin"
for f in container.sh container-size.sh checkout-id.sh checkout-resources.sh seed-volumes.sh; do
    cp "$here/$f" "$fake/scripts/$f"
done
cp "$here/../devkit.conf" "$fake/devkit.conf"
git init --quiet "$fake"
git -C "$fake" -c user.name=t -c user.email=t@example.org commit --quiet --allow-empty -m start

# `run` records its argv in $ARGV_FILE and holds until $HOLD exists - or $work/stop, which the
# cleanup writes so that nothing is left behind.
cat > "$work/bin/podman" <<'STUB'
#!/bin/sh
case "$1" in
    image | volume | rm) exit 0 ;;
    inspect) exit 1 ;;
    run)
        shift
        printf '%s\n' "$@" > "$ARGV_FILE"
        n=0
        while [ -n "${HOLD:-}" ] && [ ! -e "$HOLD" ] && [ ! -e "$WORK/stop" ] && [ "$n" -lt 300 ]; do
            sleep 0.1
            n=$((n + 1))
        done
        exit "${RUN_STATUS:-0}"
        ;;
    *) echo "stub: unexpected call: $*" >&2; exit 64 ;;
esac
STUB
chmod +x "$work/bin/podman"

# shellcheck source=scripts/container-size.sh
. "$here/container-size.sh"
m1=$(gate_memory 1)
m2=$(gate_memory 2)
m4=$(gate_memory 4)
m6=$(gate_memory 6)

# A machine of $1 MiB, with $2 available (all of it by default). Nothing reads the second any more;
# it is there so that a change which starts sizing from it again is seen to.
machine() {
    printf 'MemTotal: %d kB\nMemFree: 0 kB\nMemAvailable: %d kB\n' $(($1 * 1024)) $((${2:-$1} * 1024)) \
        > "$work/meminfo"
}
# A machine of $1 slots of $2 MiB each.
slots_of() {
    machine $(($1 * $2 + GATE_SPARE_MIB))
}

# Start container.sh as run $1, with the settings that follow, in the background, from the copy in
# $copy (the repository above by default), under $shell (the script's own by default), running $cmd
# (`true` by default). It holds once it reaches the runtime, until `let_go $1`. Whatever the
# environment this test runs in sets - a container's own DEVKIT_TIMEOUT, CI on a runner - is cleared
# first.
start() {
    name=$1
    shift
    : > "$work/$name.argv"
    rm -f "$work/$name.hold"
    (
        unset DEVKIT_TIMEOUT DEVKIT_MEMORY PYTEST_WORKERS CI DEVKIT_CONTAINER_NAME DEVKIT_DETACH DEVKIT_PORT DEVKIT_PYTHON
        export WORK="$work" ARGV_FILE="$work/$name.argv" HOLD="$work/$name.hold" \
            PATH="$work/bin:$PATH" DEVKIT_RUNTIME=podman DEVKIT_ISOLATED='' DEVKIT_NODE_INSTALL=skip \
            DEVKIT_MEMINFO="$work/meminfo" DEVKIT_NPROC=16 DEVKIT_GATE_POLL=0.2 DEVKIT_SIZE_WORKERS=6
        # shellcheck disable=SC2086  # an empty $shell is no word at all, and $cmd is several
        exec env "$@" ${shell:-} "${copy:-$fake}/scripts/container.sh" ${cmd:-true}
    ) > "$work/$name.out" 2>&1 &
    echo $! > "$work/$name.pid"
}

# Whether $1 becomes true within $2 tenths of a second.
within() {
    n=0
    while ! eval "$1"; do
        [ "$n" -lt "$2" ] || return 1
        sleep 0.1
        n=$((n + 1))
    done
}

# Whether process $1 has ended: gone, or a zombie nobody has waited for yet - which `kill -0` cannot
# tell from a live one.
ended() {
    case $(sed 's/.*) //' "/proc/$1/stat" 2>/dev/null | cut -c1) in
        '' | Z | X) return 0 ;;
        *) return 1 ;;
    esac
}

# Let run $1 go, and wait for it; its status is in $status. Bounded: a run still going ten seconds
# after it was let go is a failure, and is stopped, rather than a test that never ends.
let_go() {
    touch "$work/$1.hold"
    status=0
    # let go already
    [ -f "$work/$1.pid" ] || return 0
    pid=$(cat "$work/$1.pid")
    if ! within "ended $pid" 100; then
        fail "run $1 ends once it is let go"
        kill -KILL "$pid" 2>/dev/null || true
    fi
    status=0
    wait "$pid" || status=$?
    rm -f "$work/$1.pid"
}

# Start run $1 and let it go at once.
once() {
    name=$1
    start "$@"
    let_go "$name"
}

reached() {
    within "[ -s '$work/$1.argv' ]" "${2:-50}"
}

# Whether run $1 is waiting for a slot, and not running.
waits() {
    within "grep -q 'waiting for one of' '$work/$1.out'" 50 && [ ! -s "$work/$1.argv" ]
}

# How many of the runs named are running.
running() {
    n=0
    for r in "$@"; do
        [ -f "$work/$r.pid" ] && [ -s "$work/$r.argv" ] && n=$((n + 1))
    done
    echo "$n"
}

# What run $1 asked the runtime for, before the image name: after it is the command, whose own
# `PYTEST_WORKERS=` on a make line is not a flag.
flags_of() {
    sed -n '/^devkit-dev$/q;p' "$work/$1.argv"
}

workers_of() {
    flags_of "$1" | sed -n 's/^PYTEST_WORKERS=//p'
}

memory_of() {
    flags_of "$1" | grep -A1 -xF -- '--memory' | tail -n 1
}

deadline_of() {
    flags_of "$1" | sed -n 's/^DEVKIT_TIMEOUT=//p'
}

# How many lines slot $1 says of who holds it.
holder_lines() {
    wc -l < "$fake/.git/devkit-gate-slot.$1" | tr -d ' '
}

# --- what is not sized -----------------------------------------------------------------------

slots_of 1 "$m6"
once plain DEVKIT_SIZE_WORKERS=0
[ "$(memory_of plain)" = 6g ] || fail "DEVKIT_SIZE_WORKERS=0 keeps the fixed cap"
[ -z "$(workers_of plain)" ] || fail "and gives make no worker count, so the Makefile's default holds"
[ ! -e "$fake/.git/devkit-gate-slot.0" ] || fail "and takes no slot"

once plain_workers DEVKIT_SIZE_WORKERS=0 PYTEST_WORKERS=3
[ "$(workers_of plain_workers)" = 3 ] || fail "PYTEST_WORKERS reaches make in a run that is not sized"

once ci CI=true
[ "$(memory_of ci)" = 6g ] || fail "CI keeps the fixed cap, though the command asked to be sized"
[ -z "$(workers_of ci)" ] || fail "and the Makefile's worker count"
[ "$(deadline_of ci)" = 3600 ] || fail "and the hour's deadline"
[ ! -e "$fake/.git/devkit-gate-slot.0" ] || fail "and takes no slot"

once detached DEVKIT_DETACH=1
[ -z "$(workers_of detached)" ] || fail "a container meant to outlive this shell is not sized"

once unread DEVKIT_MEMINFO=/nonexistent
[ "$(memory_of unread)" = 6g ] || fail "a machine whose memory cannot be read keeps the fixed cap"

once ci_false CI=false
[ -n "$(workers_of ci_false)" ] || fail "CI=false is not CI"
once ci_zero CI=0
[ -n "$(workers_of ci_zero)" ] || fail "nor is CI=0"

once badsize DEVKIT_SIZE_WORKERS=lots
[ "$status" -eq 2 ] || fail "a DEVKIT_SIZE_WORKERS that is not a count is refused"
once badworkers PYTEST_WORKERS=lots
[ "$status" -eq 2 ] || fail "a PYTEST_WORKERS that is not a count is refused"
once badmemory DEVKIT_MEMORY=6.5g
[ "$status" -eq 2 ] || fail "a DEVKIT_MEMORY this cannot read is refused, not taken for none"
[ ! -s "$work/badmemory.argv" ] || fail "and nothing runs"
grep -q 'a fraction, a t or a space is refused' "$work/badmemory.out" || fail "and says which forms it refuses"

# --- the command says whether it is a run of the whole suite ----------------------------------

# given to container.sh directly, with no target to set DEVKIT_SIZE_WORKERS
for c in 'make test' 'make test-python' 'make verify' 'make verify-fresh' 'uv run scripts/ci/verify.py'; do
    cmd=$c
    once direct -u DEVKIT_SIZE_WORKERS
    cmd=''
    [ "$(workers_of direct)" = 6 ] || fail "\`scripts/container.sh $c\` is sized, as the target that runs it is"
    [ "$(memory_of direct)" = "${m6}m" ] || fail "and capped to it, not at the fixed 6g ($c)"
done
cmd='make test-coverage'
once direct_coverage -u DEVKIT_SIZE_WORKERS
cmd=''
[ "$(workers_of direct_coverage)" = 1 ] || fail "\`make test-coverage\` is sized for the one worker it uses"
# the fast stage runs a selection, which waiting behind a gate would cost more than it saves
cmd='uv run python scripts/ci/fast_stage.py run --base HEAD -- -n 6'
once direct_fast -u DEVKIT_SIZE_WORKERS
cmd=''
[ -z "$(workers_of direct_fast)" ] || fail "the fast stage is not sized"
[ "$(memory_of direct_fast)" = 6g ] || fail "and keeps the fixed cap"
cmd='make test PYTEST_WORKERS=2'
once direct_given -u DEVKIT_SIZE_WORKERS
cmd=''
[ "$(workers_of direct_given)" = 2 ] || fail "a PYTEST_WORKERS on the make line is the count"
[ "$(memory_of direct_given)" = "${m2}m" ] || fail "and the cap is what that count needs"
cmd='make check'
once direct_check -u DEVKIT_SIZE_WORKERS
cmd=''
[ "$(memory_of direct_check)" = 6g ] || fail "a command that is no run of the whole suite is not sized"
cmd='make verify'
once direct_off DEVKIT_SIZE_WORKERS=0
cmd=''
[ "$(memory_of direct_off)" = 6g ] || fail "and DEVKIT_SIZE_WORKERS=0 turns the sizing off for one that is"

# --- what one run is given -------------------------------------------------------------------

slots_of 1 "$m6"
once roomy
[ "$status" -eq 0 ] || fail "a sized run succeeds when its command does"
[ "$(workers_of roomy)" = 6 ] || fail "a slot of six workers' memory gives the run all six"
[ "$(memory_of roomy)" = "${m6}m" ] || fail "and their memory as the cap"
[ "$(deadline_of roomy)" = 3600 ] || fail "and the hour's deadline"
grep -q "6 pytest workers in ${m6}m, deadline 3600s (slot 0 of 1)" "$work/roomy.out" ||
    fail "and says what it was given, and which slot"

# the memory available is not what sizes a run: a slot is
machine $((m6 + GATE_SPARE_MIB)) 100
once unavailable
[ "$(workers_of unavailable)" = 6 ] || fail "a run is sized from MemTotal, not from what happens to be free"

slots_of 1 "$m4"
once four
[ "$(workers_of four)" = 4 ] || fail "a slot holds as many workers as fit it"
[ "$(memory_of four)" = "${m4}m" ] || fail "and the cap is what they need"
[ "$(deadline_of four)" = 5400 ] || fail "and fewer workers are given longer, in proportion"

slots_of 1 "$m2"
once two_workers
[ "$(deadline_of two_workers)" = 7200 ] || fail "but no more than two hours"

slots_of 1 "$m6"
once cores DEVKIT_NPROC=3
[ "$(workers_of cores)" = 3 ] || fail "no more workers than cores"

once coverage DEVKIT_SIZE_WORKERS=1
[ "$(workers_of coverage)" = 1 ] || fail "a serial command is given one worker"
[ "$(deadline_of coverage)" = 3600 ] ||
    fail "and the hour: it has all the workers it can use, so nothing is stretched"

once given PYTEST_WORKERS=2
[ "$(workers_of given)" = 2 ] || fail "PYTEST_WORKERS given outright is the count"
[ "$(memory_of given)" = "${m2}m" ] || fail "and the cap is what that count needs"

once octal PYTEST_WORKERS=08
[ "$(workers_of octal)" = 8 ] || fail "PYTEST_WORKERS=08 is eight, not an octal error"
[ "$(deadline_of octal)" = 3600 ] || fail "and more workers than the command's own count shorten no deadline"

once auto PYTEST_WORKERS=auto
[ "$(workers_of auto)" = 6 ] || fail "PYTEST_WORKERS=auto is sized, as xdist's auto would be"

once serial PYTEST_WORKERS=0
[ "$(workers_of serial)" = 1 ] || fail "PYTEST_WORKERS=0, serial to the Makefile, is one worker"
[ "$(memory_of serial)" = "${m1}m" ] || fail "and holds what one worker needs"

once given_deadline DEVKIT_TIMEOUT=90 PYTEST_WORKERS=1
[ "$(deadline_of given_deadline)" = 90 ] || fail "DEVKIT_TIMEOUT given outright is not stretched"

given_g=$(((m2 + 1023) / 1024))
once given_memory DEVKIT_MEMORY="${given_g}g"
[ "$(memory_of given_memory)" = "${given_g}g" ] || fail "DEVKIT_MEMORY given outright is the cap, as it was given"
[ "$(workers_of given_memory)" = "$(gate_fit $((given_g * 1024)) 16 6)" ] ||
    fail "and the workers are as many as it holds"

once uncapped DEVKIT_MEMORY=0
grep -qxF -- '--memory' "$work/uncapped.argv" && fail "DEVKIT_MEMORY=0 runs with no cap"
[ "$(workers_of uncapped)" = 6 ] || fail "and is sized all the same"

# a machine too small for one worker of the suite: one worker, and a cap of what the slot holds
machine $((m1 - 1 + GATE_SPARE_MIB))
once small_machine
[ "$(workers_of small_machine)" = 1 ] || fail "a machine too small for one worker still runs one"
[ "$(memory_of small_machine)" = "$((m1 - 1))m" ] || fail "capped at what it has, not at what one needs"
grep -q "one worker needs ${m1}m" "$work/small_machine.out" || fail "and says so"

# a machine with less than the spare: no cap at all rather than one podman refuses
machine 512
once tiny_machine
[ "$status" -eq 0 ] || fail "a machine with less memory than the spare still runs"
[ "$(workers_of tiny_machine)" = 1 ] || fail "with one worker"
[ -z "$(memory_of tiny_machine)" ] || fail "and no cap, rather than $(memory_of tiny_machine)"
grep -q 'no cap podman takes' "$work/tiny_machine.out" || fail "and says why it has none"

# two slots: each sized for its share of the machine and of its cores
slots_of 2 "$m6"
once halves DEVKIT_NPROC=8
[ "$(workers_of halves)" = 4 ] || fail "a run on a machine of two slots takes half the cores"
[ "$(memory_of halves)" = "${m4}m" ] || fail "and the memory four need"
# where the cores and the command allow more, the memory of one slot is what bounds a run
once half_memory DEVKIT_NPROC=32 DEVKIT_SIZE_WORKERS=12
[ "$(workers_of half_memory)" = 6 ] || fail "a run on a machine of two slots takes half the memory"
# one core between two slots: each has one, not none
once one_core DEVKIT_NPROC=1
[ "$(workers_of one_core)" = 1 ] || fail "one core shared between two slots still gives each a worker"
[ "$(memory_of one_core)" = "${m1}m" ] || fail "and the memory one worker needs, not the whole slot"
grep -q 'one worker needs' "$work/one_core.out" && fail "and no warning: the memory fits"

# where flock cannot lock at all, the run is sized and not kept, and says so - rather than taking
# every slot for held and waiting for ever
mkdir -p "$work/brokenflock"
printf '#!/bin/sh\nexit 71\n' > "$work/brokenflock/flock"
chmod +x "$work/brokenflock/flock"
slots_of 1 "$m6"
start broken_flock PATH="$work/brokenflock:$work/bin:$given_path"
if reached broken_flock; then
    [ "$(workers_of broken_flock)" = 6 ] || fail "a run with a flock that fails is sized all the same"
    grep -q 'sized, but not kept' "$work/broken_flock.out" || fail "and says it is not kept from other runs"
else
    fail "a run with a flock that fails starts, rather than taking every slot for held"
fi
let_go broken_flock

# a common git directory nobody can create files in: the same. Root creates files anywhere, so
# that half is shown only where the test is not root; a probe file that is a directory is shown
# everywhere.
rm -f "$fake/.git/devkit-gate-probe" "$fake/.git"/devkit-gate-slot.*
mkdir "$fake/.git/devkit-gate-probe"
once probe_dir
grep -q 'sized, but not kept' "$work/probe_dir.out" || fail "a slot directory whose files cannot be opened keeps no slot"
[ "$(workers_of probe_dir)" = 6 ] || fail "and the run is sized all the same"
rmdir "$fake/.git/devkit-gate-probe"
if [ "$(id -u)" -ne 0 ]; then
    chmod a-w "$fake/.git"
    once unwritable
    chmod u+w "$fake/.git"
    grep -q 'sized, but not kept' "$work/unwritable.out" || fail "a common git directory nobody can write keeps no slot"
fi

# a copy that is in no repository has no slots to share, and is sized all the same
mkdir -p "$work/plain/scripts"
cp "$fake"/scripts/*.sh "$work/plain/scripts/"
cp "$fake/devkit.conf" "$work/plain/devkit.conf"
slots_of 1 "$m6"
copy="$work/plain"
once unshared
copy=''
[ "$status" -eq 0 ] || fail "a run with no git directory for slots still runs"
[ "$(workers_of unshared)" = 6 ] || fail "and is sized"
grep -q 'no slot' "$work/unshared.out" || fail "and says it is not kept from other runs"

# --- one slot, several runs -------------------------------------------------------------------

slots_of 1 "$m6"
start holder
reached holder || fail "a run takes the free slot"
holder=$(cat "$work/holder.pid")
grep -q " $holder " "$fake/.git/devkit-gate-slot.0" ||
    fail "and writes which checkout and process holds it, for people to read"
start waiter
waits waiter || fail "a second run on a machine of one slot waits"
grep -q "(pid $holder)" "$work/waiter.out" || fail "and says who holds the slot"
sleep 1
[ "$(grep -c 'waiting for' "$work/waiter.out")" -eq 1 ] ||
    fail "and says so once while nothing changes, not at every try"
let_go holder
reached waiter || fail "and starts once the slot is let go"
[ "$(holder_lines 0)" -eq 1 ] || fail "and the slot's file names it alone, not every run that held it"
let_go waiter

# a waiting run is woken by the kernel the moment the slot is let go, and so goes before a run that
# arrives after - even when it would not look again for half a minute
start holder
reached holder || fail "the holder starts again"
start blocked DEVKIT_GATE_POLL=30
waits blocked || fail "a run waits, looking again only every 30s"
let_go holder
start newcomer
reached blocked 30 || fail "and takes the slot when it is let go, without waiting to look again"
waits newcomer || fail "before a run that arrived after it"
let_go blocked
reached newcomer || fail "which then has its turn"
let_go newcomer

# a slot whose file cannot be opened is passed over, not the end of the run
slots_of 2 "$m6"
start holder
reached holder || fail "a run takes slot 0 of two"
mkdir "$fake/.git/devkit-gate-slot.1"
start passed_over
waits passed_over || fail "a run that cannot open slot 1 waits for slot 0, and does not end"
let_go holder
reached passed_over || fail "and takes slot 0 when it is let go"
let_go passed_over
rmdir "$fake/.git/devkit-gate-slot.1"
slots_of 1 "$m6"

# DEVKIT_MEMORY given, or 0, still waits for a slot: it is a run of the whole suite all the same
start holder
reached holder || fail "the holder starts again"
start given_waits DEVKIT_MEMORY="${given_g}g"
waits given_waits || fail "a run given its memory still waits for a slot"
start uncapped_waits DEVKIT_MEMORY=0
waits uncapped_waits || fail "and so does one given no cap"
let_go holder
within "[ \$(running given_waits uncapped_waits) -eq 1 ]" 50 || fail "one of them starts once the slot is let go"
for r in given_waits uncapped_waits; do
    [ -s "$work/$r.argv" ] || continue
    let_go "$r"
    break
done
within "[ \$(running given_waits uncapped_waits) -eq 1 ]" 50 || fail "and the other after it"
let_go given_waits
let_go uncapped_waits

# three started together: one runs, two wait, and all three end, one after the other
for r in one two three; do start "$r"; done
within "[ \$(running one two three) -ge 1 ]" 50 || fail "one of three runs started together runs"
sleep 1
[ "$(running one two three)" -eq 1 ] || fail "and only one, on a machine of one slot"
ended_runs=0
for round in 1 2 3; do
    within "[ \$(running one two three) -eq 1 ]" 50 || fail "one run at a time (round $round)"
    for r in one two three; do
        [ -f "$work/$r.pid" ] && [ -s "$work/$r.argv" ] || continue
        let_go "$r"
        [ "$status" -eq 0 ] || fail "run $r ends as its command does"
        ended_runs=$((ended_runs + 1))
        break
    done
done
[ "$ended_runs" -eq 3 ] || fail "all three runs end"

# two slots: two run at once, the third waits
slots_of 2 "$m6"
start a
start b
{ reached a && reached b; } || fail "two runs start at once on a machine of two slots"
start c
waits c || fail "and a third waits"
let_go a
reached c || fail "and starts when one of them ends"
let_go b
let_go c

# a linked worktree shares the slots of the repository it is part of
slots_of 1 "$m6"
git -C "$fake" worktree add --quiet --detach "$work/linked"
mkdir -p "$work/linked/scripts"
cp "$fake"/scripts/*.sh "$work/linked/scripts/"
cp "$fake/devkit.conf" "$work/linked/devkit.conf"
start holder
reached holder || fail "a run in the main checkout takes the slot"
copy="$work/linked"
start linked_waiter
copy=''
waits linked_waiter || fail "a run in a linked worktree waits for the same slot"
let_go holder
reached linked_waiter || fail "and takes it when it is let go"
let_go linked_waiter

# --- a holder that dies -----------------------------------------------------------------------

# SIGKILL to container.sh: nothing of its own runs on the way out. The slot is held for as long as
# anything it started holds the descriptor - here the stub client; under podman also conmon and the
# network helper, so until the container ends - and let go when that ends, by the kernel.
start killed
reached killed || fail "a run to kill starts"
start after_kill
waits after_kill || fail "a run waits behind it"
kill -KILL "$(cat "$work/killed.pid")"
sleep 1
[ ! -s "$work/after_kill.argv" ] || fail "the slot stays held while the runtime's client runs on"
touch "$work/killed.hold"
reached after_kill || fail "and is let go when that ends, though nothing released it"
wait "$(cat "$work/killed.pid")" 2>/dev/null || true
rm -f "$work/killed.pid"
let_go after_kill

# --- stopping a run that waits, under every shell there is ------------------------------------

start holder
reached holder || fail "the holder starts again"
for s in sh bash dash; do
    command -v "$s" > /dev/null 2>&1 || continue
    shell=$s
    start "stopped_$s"
    shell=''
    waits "stopped_$s" || fail "a run under $s waits"
    stopped=$(cat "$work/stopped_$s.pid")
    kill -TERM "$stopped"
    within "ended $stopped" 20 || fail "and TERM ends it at once, under $s"
    wait "$stopped" 2>/dev/null || true
    rm -f "$work/stopped_$s.pid"
done
start after_stopped
waits after_stopped || fail "the runs stopped while waiting took no slot with them"
let_go holder
reached after_stopped || fail "and the next run takes the slot when it is let go"
let_go after_stopped

# The targets of a service's Makefile that call container.sh are the service's to test.

if [ "$failures" -ne 0 ]; then
    echo "$failures check(s) failed" >&2
    exit 1
fi

echo "container-size.sh: all checks passed"
