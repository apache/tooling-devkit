# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Everything that gates a push, at once, and only what changed since it last passed.

`make verify` runs each stage as the make target of the same name, all of them at the same time:
pytest keeps up to six workers busy, and the rest - the hooks, the linters, vitest, the behaviour record and
the quality ratchet - fit beside it on the cores it leaves, so the gate takes about as long as its
longest stage rather than the sum of them. Each stage writes its own log under state/verify/, and
what is printed is one line per stage, and the end of the log of one that failed.

A stage that passed is not run again until something it reads changes. What it reads is its key: the
content of its files - tracked, staged or untracked, as they are in the working tree, so an edit the
gate has not seen is a change - the commands its make target runs (`make -n`, so that a comment in the
Makefile is not, for a stage that does not read the Makefile itself), and what else the stage depends
on (`EXTRAS`). The key is taken before the stage
runs and again after it, and a pass is recorded only when the two agree: a hook that rewrote a file
while pytest was reading it leaves nothing recorded, and the next run runs both again.

A stage whose files are only some of the tree says which (`Stage.paths`), and each of those lists is
a claim that the stage reads nothing else. Where a stage reads the whole tree it says so, and a
change anywhere runs it.

    scripts/container.sh uv run scripts/ci/verify.py                 # what `make container-verify` runs
    scripts/container.sh uv run scripts/ci/verify.py --fresh         # run every stage, passed or not
    scripts/container.sh uv run scripts/ci/verify.py test-python     # one stage

Each of these is sized to the machine and holds one of its gate slots, as `make container-verify`
is (scripts/container-size.sh).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
from collections.abc import Callable

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
STATE = ROOT / "state" / "verify"

# Lines of a failed stage's log printed under its verdict; the whole log is a path away.
_TAIL = 60


@dataclasses.dataclass(frozen=True)
class Stage:
    name: str
    """The make target, and the name of the log and the record."""
    paths: tuple[str, ...] | None = None
    """The prefixes of the files the stage reads, or None for the whole tree."""
    extras: tuple[str, ...] = ()
    """Names in `EXTRAS`: what the stage depends on that is not a file of the tree."""
    reads_makefile: bool = False
    """Whether the Makefile is a file the stage reads, rather than only where its command comes from -
    which `recipe` covers, so that a comment there runs nothing again."""
    longest: bool = False
    """The stage the gate waits for. The others run niced, so that the cores go to it first and the
    rest fill what it leaves."""


def _corpus() -> str:
    """The published minutes, where they have been fetched: the corpus tests skip without them, so
    fetching them, or updating them, is a change to what pytest checks. Names, sizes and times rather
    than contents - 38MB is read once by the tests, and should not be read again to decide whether to."""
    corpus = pathlib.Path(os.environ.get("MINUTES_CORPUS") or ROOT / "state" / "minutes-corpus")
    if not corpus.is_dir():
        return "no corpus"
    found = sorted(corpus.parent.glob("podlings.xml")) + sorted(corpus.rglob("board_minutes_*.txt"))
    return "\n".join(f"{p.relative_to(corpus.parent)} {p.stat().st_size} {p.stat().st_mtime_ns}" for p in found)


def _trailers() -> str:
    """The messages of this branch's own commits, which is where an allowance is read from
    (`Behaviour-Allow:`, `Quality-Allow:`): a trailer added by an amend changes what the stage says."""
    base = _git("merge-base", os.environ.get("VERIFY_REF", "origin/main"), "HEAD", check=False)
    return _git("log", "--format=%B%x00", f"{base}..HEAD", check=False) if base else "no merge base"


def _file(relative: str, *, named_by: str | None = None) -> Callable[[], str]:
    """What a file holds, read when the key is taken - from the path the variable `named_by` gives,
    where the Makefile passes one, since that is the file the stage reads."""

    def read() -> str:
        named = os.environ.get(named_by, "") if named_by else ""
        path = ROOT / (named or relative)
        return path.read_text(encoding="utf-8") if path.is_file() else f"no {path}"

    return read


EXTRAS: dict[str, Callable[[], str]] = {
    "corpus": _corpus,
    "trailers": _trailers,
    # what the two comparisons compare against, which `make snapshot-base` and `make quality-base` write
    "behaviour-base": _file("state/behaviour-base.behaviour-record.json"),
    "quality-base": _file("state/quality-base.json", named_by="QUALITY_BASE"),
    # a build of the frontend, ignored by git: where there is one, the tests read it rather than the
    # fixture's copy (_ensure_static_assets in tests/conftest.py)
    "static-assets": _file("app/client/static/assets/manifest.json"),
}

# The frontend's tests read two fixtures under tests/data (agenda-model.test.ts, namesearch.test.ts),
# and eslint reads the repository's .gitignore (eslint.config.js).
_FRONTEND = ("assets/", "tests/data/", ".gitignore")

STAGES = (
    # the hooks lint every file, the Makefile among them
    Stage("check-all", reads_makefile=True),
    Stage("lint", paths=_FRONTEND),
    Stage("test-python", extras=("corpus", "static-assets"), longest=True),
    Stage("test-frontend", paths=_FRONTEND),
    # a change to the Makefile is one the selection cannot see through, so it records everything:
    # see EVERYTHING_WHEN in behaviour_selection.py
    Stage("snapshot", extras=("behaviour-base", "trailers", "static-assets"), reads_makefile=True),
    Stage("quality", extras=("quality-base", "trailers")),
)

# Settings a run reads from the environment that change what it checks - PYTEST_ADDOPTS among them,
# since `-k` or `--lf` there runs some of the suite and would otherwise record a pass of all of it.
# Make's own variables reach the key through `make -n` instead, all but PYTEST_WORKERS (`recipe`).
_ENVIRONMENT = ("DEVKIT_PROPERTY_EXAMPLES", "MINUTES_CORPUS", "DEVKIT_PYTHON", "PYTEST_ADDOPTS")


def _git(*arguments: str, check: bool = True, stdin: str | None = None) -> str:
    finished = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, input=stdin)
    if check and finished.returncode != 0:
        raise SystemExit(f"git {' '.join(arguments)}: {finished.stderr.strip()}")
    return finished.stdout.strip() if finished.returncode == 0 else ""


def tree() -> dict[str, str]:
    """Every file of the working tree - tracked, staged, or untracked and not ignored by a .gitignore -
    and the hash of what it holds now. A tracked file that is gone is listed as gone.

    Only the .gitignore files decide what is ignored, not .git/info/exclude or a global excludes file:
    a test file hidden there is still one pytest collects."""
    listed = _git("ls-files", "-z", "--cached", "--others", "--exclude-per-directory=.gitignore").split("\0")
    paths = sorted({p for p in listed if p})
    present = [p for p in paths if (ROOT / p).is_file()]
    hashes = _git("hash-object", "--stdin-paths", stdin="\n".join(present)).splitlines() if present else []
    found = dict(zip(present, hashes, strict=True))
    return {p: found.get(p, "gone") for p in paths}


def recipe(stage: Stage) -> str:
    """What the stage's make target runs, as make prints it without running it - with the worker count
    pinned, since scripts/container-size.sh chooses it from the memory free when the gate starts, and a
    count is how long the suite takes rather than what it checks."""
    finished = subprocess.run(
        [os.environ.get("MAKE", "make"), "--no-print-directory", "-n", stage.name, "PYTEST_WORKERS=any"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if finished.returncode != 0:
        raise SystemExit(f"make -n {stage.name}: {finished.stderr.strip()}")
    return finished.stdout


def key(stage: Stage, files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for part in (stage.name, recipe(stage), sys.version):
        digest.update(part.encode() + b"\0")
    for name in _ENVIRONMENT:
        digest.update(f"{name}={os.environ.get(name, '')}\0".encode())
    for path, blob in files.items():
        if path == "Makefile" and not stage.reads_makefile:
            continue
        if stage.paths is None or path.startswith(stage.paths):
            digest.update(f"{path} {blob}\0".encode())
    for extra in stage.extras:
        digest.update(f"{extra}\0{EXTRAS[extra]()}\0".encode())
    return digest.hexdigest()


def _record(stage: Stage) -> pathlib.Path:
    return STATE / f"{stage.name}.passed"


def passed(stage: Stage) -> dict[str, str] | None:
    try:
        return json.loads(_record(stage).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


@dataclasses.dataclass(frozen=True)
class Outcome:
    stage: Stage
    verdict: str
    """"passed", "failed" or "unchanged"."""
    seconds: float
    log: pathlib.Path


def run(stage: Stage, *, fresh: bool) -> Outcome:
    log = STATE / f"{stage.name}.log"
    before = key(stage, tree())
    earlier = None if fresh else passed(stage)
    if earlier is not None and earlier.get("key") == before:
        return Outcome(stage, "unchanged", 0.0, log)
    _record(stage).unlink(missing_ok=True)
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as out:
        finished = subprocess.run(
            [
                *(() if stage.longest else ("nice", "-n", "10")),
                os.environ.get("MAKE", "make"),
                "--no-print-directory",
                stage.name,
            ],
            cwd=ROOT,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    seconds = time.monotonic() - started
    if finished.returncode != 0:
        return Outcome(stage, "failed", seconds, log)
    if key(stage, tree()) == before:
        when = datetime.datetime.now(tz=datetime.UTC).isoformat(timespec="seconds")
        _record(stage).write_text(json.dumps({"key": before, "at": when}) + "\n", encoding="utf-8")
    return Outcome(stage, "passed", seconds, log)


def report(outcome: Outcome) -> str:
    name, log = outcome.stage.name, outcome.log.relative_to(ROOT)
    if outcome.verdict == "unchanged":
        at = (passed(outcome.stage) or {}).get("at", "earlier")
        return f"{name}: unchanged since it passed at {at}, not run"
    if outcome.verdict == "passed":
        return f"{name}: passed in {outcome.seconds:.0f}s ({log})"
    lines = outcome.log.read_text(encoding="utf-8", errors="replace").splitlines()[-_TAIL:]
    return "\n".join(
        [f"{name}: FAILED in {outcome.seconds:.0f}s - the end of {log}:", *(f"    {line}" for line in lines)]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stages", nargs="*", metavar="STAGE", help=", ".join(s.name for s in STAGES))
    parser.add_argument("--fresh", action="store_true", help="run every stage, whether it passed before or not")
    args = parser.parse_args()
    unknown = sorted(set(args.stages) - {s.name for s in STAGES})
    if unknown:
        parser.error(f"no stage {', '.join(unknown)}: the stages are {', '.join(s.name for s in STAGES)}")
    chosen = [s for s in STAGES if not args.stages or s.name in args.stages]
    STATE.mkdir(parents=True, exist_ok=True)

    print(f"verify: {len(chosen)} stages at once - {', '.join(s.name for s in chosen)}", flush=True)
    outcomes: list[Outcome] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(chosen)) as pool:
        futures = [pool.submit(run, stage, fresh=args.fresh) for stage in chosen]
        for future in concurrent.futures.as_completed(futures):
            outcomes.append(future.result())
            print(report(outcomes[-1]), flush=True)

    failed = [o.stage.name for o in outcomes if o.verdict == "failed"]
    if failed:
        print(f"verify: FAILED - {', '.join(failed)}")
        return 1
    print("verify: every stage passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
