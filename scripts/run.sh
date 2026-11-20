#!/bin/bash
set -eu

# This script is used by the service in Puppet

# shellcheck source=/dev/null
source .venv/bin/activate

BIND=$(python3 app/config.py --bind)
ACCESS_LOG=$(python3 app/config.py --access-log)
PID_FILE=$(python3 app/config.py --pid-file)

# One process, and explicitly so: the app keeps an in-memory singleton - the websocket broker -
# that only makes sense with exactly one worker.
#
# That used to be workers=1, hypercorn's own default, left unset. But hypercorn's non-zero
# path still spawns that one worker as a `multiprocessing.Process` marked daemon=True, purely
# so it can tell the difference between "no workers configured" and "one worker, spawned like
# any other" - and a daemonic process is not allowed to have children of its own. Minutes-pages
# generation parses the corpus and extracts each meeting's content in a ProcessPoolExecutor
# (app/actions/minutes_site.py) to spread genuinely CPU-bound work across cores, and that pool
# is itself built out of multiprocessing.Process - so under workers=1 it fails outright with
# "AssertionError: daemonic processes are not allowed to have children" the first time the
# corpus is large enough to use it. workers=0 runs the worker function directly in this
# process instead of spawning a copy of it, so it is never marked daemon and the pool can
# spawn normally - same one process, same singletons, no restriction that was never about
# our own process tree to begin with.
exec hypercorn server:application -b "${BIND}" --access-logfile "${ACCESS_LOG}" --pid "${PID_FILE}" --worker-class uvloop --workers 0
