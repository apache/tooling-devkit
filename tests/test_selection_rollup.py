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

"""What the weekly rollup of the selection audit says (`scripts/ci/selection_rollup.py`).

What it reads was uploaded by pull requests' runs, so each test hands it records as an artifact would and
asks what reaches the issue body: what is counted, what is read at all, and what a record can make it say.
"""

import importlib.util
import json
import pathlib
import sys
import types

import pytest

_CI = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ci"


def _load(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, _CI / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load("fast_stage_record")
_load("fast_stage")
audit_module = _load("selection_audit")
rollup_module = _load("selection_rollup")

REPOSITORY = "apache/tooling-agenda"
UNTIL = "2026-11-21"


def _sha(letter: str) -> str:
    return letter * 40


def _failure(test: str, outcome: str, selected: bool = False, link: str | None = None) -> dict:
    return {"test": test, "file": None, "outcome": outcome, "selected": selected, "rules": [], "link": link}


def _record(pr: object, pr_head: str, verdict: str, failures: list[dict], **more: object) -> dict:
    record = {"version": 1, "audited": True, "pr": pr, "pr_head": pr_head, "head": "f" * 40, "verdict": verdict}
    return record | {"changed": ["app/a.py"], "failures": failures, "run": "https://example.org/run"} | more


class Week:
    """A directory of runs' records, and the list of runs the workflow writes beside it."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root, self.runs = root, []

    def add(self, run: int, record: object, head: str | None = None, repository: str = REPOSITORY) -> None:
        sha = head or (record.get("pr_head") if isinstance(record, dict) else None) or _sha("0")
        self.runs.append(f"{run}\t{sha}\t{repository}")
        (self.root / str(run)).mkdir(parents=True)
        written = record if isinstance(record, str) else json.dumps(record)
        (self.root / str(run) / "selection-audit.json").write_text(written)

    def load(self) -> object:
        return rollup_module.load(self.root, rollup_module.read_runs("\n".join(self.runs)), REPOSITORY)

    def body(self, previous: str = "") -> str:
        return rollup_module.rollup(self.load(), UNTIL, previous)


@pytest.fixture
def week(tmp_path: pathlib.Path) -> Week:
    """Five pull requests: one caught, one missed twice (two pushes) beside a flake, one sent with its file held,
    one clean, and one that could not be audited; one push of #1 was run twice."""
    week = Week(tmp_path)
    week.add(10, _record(1, _sha("a"), "fails", [_failure("tests/test_a.py::test_a", "caught", True)]))
    week.add(11, _record(1, _sha("a"), "fails", [_failure("tests/test_a.py::test_a", "caught", True)]))
    missed = _failure("tests/test_b.py::test_b", "missed", link="it names `a`, the module of app/a.py")
    flake = _failure("tests/test_c.py::test_c", "flake")
    week.add(12, _record(2, _sha("b"), "passes-wrongly", [missed, dict(missed, link=None), flake]))
    week.add(13, _record(2, _sha("c"), "passes-wrongly", [_failure("tests/test_b.py::test_b", "missed")]))
    sent = [_failure("tests/test_d.py::test_d", "sent", True), _failure("tests/test_e.py::test_e", "sent")]
    week.add(14, _record(3, _sha("d"), "fails", sent))
    week.add(15, _record(4, _sha("e"), "clean", []))
    week.add(
        16, {"version": 1, "audited": False, "why": "the suite wrote no junit report", "pr": 5, "pr_head": _sha("1")}
    )
    return week


def _lines(body: str, start: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith(start)]


def test_the_headline_is_the_runs_the_stage_would_have_passed_wrongly(week: Week) -> None:
    body = week.body()
    assert "**Runs the stage would have passed wrongly: 2 of 4 runs with a real failure (50%).**" in body
    assert "| A real failure, which the stage would have failed on | 2 |" in body
    assert "| A real failure, which the stage would have passed: a miss | 2 |" in body
    assert "| Nothing failed again | 1 |" in body


def test_each_push_is_read_once_and_the_runs_say_how_many_kept_an_audit(week: Week) -> None:
    body = week.body()
    assert "7 runs of `Build and test` on this repository's pull requests; 0 from forks, not read." in body
    assert (
        "7 of 7 runs kept an audit: 6 pushes of 5 pull requests, each read once; 1 of them could not be audited."
        in body
    )


def test_the_failing_tests_are_counted_once_a_push(week: Week) -> None:
    body = week.body()
    assert "| Caught: the selection held the file | 1 |" in body
    assert "| Missed: the selection did not hold the file | 2 |" in body
    assert "| Sent to the full suite: a trigger or the 40% limit | 2, 1 in what the stage ran |" in body
    assert "| Flakes: passed when run again | 1 |" in body
    assert f"| {UNTIL} | 6 | 4 | 2 | 50% | 1 | 2 | 1 |" in body


def test_a_missed_test_is_listed_once_with_each_push_it_failed_in(week: Week) -> None:
    body = week.body()
    assert _lines(body, "- `") == ["- `tests/test_b.py::test_b`: 2 pushes of 1 pull requests"]
    run = f"https://github.com/{REPOSITORY}/actions/runs/"
    assert _lines(body, "  - #") == [f"  - #2 ([run]({run}12)): `app/a.py`", f"  - #2 ([run]({run}13)): `app/a.py`"]
    assert "  - what links them: `it names a, the module of app/a.py`" in body


def test_a_run_from_a_fork_is_counted_and_not_read(week: Week) -> None:
    week.add(
        20,
        _record(6, _sha("6"), "passes-wrongly", [_failure("tests/test_f.py::test_f", "missed")]),
        repository="someone/fork",
    )
    body = week.body()
    assert "7 runs of `Build and test` on this repository's pull requests; 1 from forks, not read." in body
    assert "test_f" not in body


def test_a_record_of_another_commit_than_its_runs_head_is_not_read(tmp_path: pathlib.Path) -> None:
    week = Week(tmp_path)
    missed = [_failure("tests/test_f.py::test_f", "missed")]
    week.add(1, _record(6, _sha("6"), "passes-wrongly", missed), head=_sha("7"))
    week.add(2, _record(7, _sha("8"), "passes-wrongly", missed, head=_sha("9")), head=_sha("9"))
    body = week.body()
    assert "0 of 2 runs kept an audit" in body and "test_f" not in body


def test_a_run_is_linked_by_its_id_never_by_what_its_record_says(week: Week) -> None:
    assert "example.org" not in week.body()


def test_records_that_are_not_ones_are_not_read(tmp_path: pathlib.Path) -> None:
    week = Week(tmp_path)
    missed = [_failure("tests/test_f.py::test_f", "missed")]
    week.add(1, _record(6, _sha("6"), "passes-wrongly", missed, version=2))
    week.add(2, "{not json")
    week.add(3, [1, 2])
    week.add(4, _record(7, _sha("7"), "no such verdict", [_failure("x", "no such outcome")]))
    body = week.body()
    assert "1 of 4 runs kept an audit" in body
    assert "**Runs the stage would have passed wrongly: 0 of 0 runs with a real failure (n/a).**" in body
    assert "None this week." in body


def test_a_line_of_the_run_list_that_is_not_one_is_left_out() -> None:
    lines = [
        f"1\t{_sha('a')}\t{REPOSITORY}",
        f"x\t{_sha('a')}\t{REPOSITORY}",
        f"2\tnot-a-sha\t{REPOSITORY}",
        "3\t",
        f"\u0663\t{_sha('a')}\tr",
    ]
    assert [run.id for run in rollup_module.read_runs("\n".join(lines))] == [1]


def test_the_pull_requests_are_listed_in_order_of_their_number(tmp_path: pathlib.Path) -> None:
    week = Week(tmp_path)
    week.add(1, _record(9, _sha("1"), "passes-wrongly", [_failure("tests/test_x.py::test_x", "missed")]))
    week.add(2, _record(3, _sha("8"), "passes-wrongly", [_failure("tests/test_y.py::test_y", "missed")]))
    assert _lines(week.body(), "- `") == [
        "- `tests/test_y.py::test_y`: 1 pushes of 1 pull requests",
        "- `tests/test_x.py::test_x`: 1 pushes of 1 pull requests",
    ]


def test_a_week_with_no_miss_says_so_and_has_no_rate(tmp_path: pathlib.Path) -> None:
    body = Week(tmp_path).body()
    assert "None this week." in body
    assert f"| {UNTIL} | 0 | 0 | 0 | n/a | 0 | 0 | 0 |" in body


def test_the_body_written_again_from_itself_is_the_same_body(week: Week) -> None:
    body = week.body()
    assert week.body(body) == body
    assert body.startswith(rollup_module.MARK + "\n")


def test_each_week_keeps_the_rows_of_the_weeks_before_it_newest_first(week: Week, tmp_path: pathlib.Path) -> None:
    first = rollup_module.rollup(Week(tmp_path / "empty").load(), "2026-11-14")
    hostile = "| 2026-11-07 | @someone | 1 | 1 | 1% | 1 | 1 | 1 |\n| \uff12\uff10\uff12\uff16-11-06 | 1 | 1 | 1 | 1% | 1 | 1 | 1 |\n"
    rows = _lines(week.body(first + hostile), "| 2026-")
    assert rows == [f"| {UNTIL} | 6 | 4 | 2 | 50% | 1 | 2 | 1 |", "| 2026-11-14 | 0 | 0 | 0 | n/a | 0 | 0 | 0 |"]


def test_two_years_of_weeks_are_kept_and_no_more(tmp_path: pathlib.Path) -> None:
    previous = "".join(
        f"| 2024-{month:02}-{day:02} | 0 | 0 | 0 | n/a | 0 | 0 | 0 |\n"
        for month in range(1, 13)
        for day in range(1, 10)
    )
    rows = _lines(Week(tmp_path).body(previous), "| 202")
    assert len(rows) == rollup_module.KEPT_WEEKS == 104
    assert rows[0].startswith(f"| {UNTIL} ") and rows[-1].startswith("| 2024-01-06 ")


def _misses(week: Week, tests: int, pushes: int = 1) -> None:
    for each in range(tests * pushes):
        failure = _failure(f"tests/test_{each % tests:03}.py::test_a", "missed")
        week.add(100 + each, _record(each, f"{each:040x}", "passes-wrongly", [failure]))


def test_a_long_list_of_misses_is_cut_and_says_so(tmp_path: pathlib.Path) -> None:
    week = Week(tmp_path)
    _misses(week, rollup_module.LISTED + 1)
    body = week.body()
    assert len(_lines(body, "- `tests/")) == rollup_module.LISTED == 25
    assert "- and 1 more tests, in the artifacts" in body


def test_a_test_missed_in_many_pushes_lists_a_few_and_says_so(tmp_path: pathlib.Path) -> None:
    week = Week(tmp_path)
    _misses(week, 1, rollup_module.PER_TEST + 1)
    body = week.body()
    assert len(_lines(body, "  - #")) == rollup_module.PER_TEST == 5
    assert "  - and 1 more pushes" in body
    assert "- `tests/test_000.py::test_a`: 6 pushes of 6 pull requests" in body


def test_a_body_past_githubs_limit_cuts_the_misses_and_keeps_every_week(tmp_path: pathlib.Path) -> None:
    """One heavy week must not cost the history: a week left out of the body is gone from the next one too."""
    week = Week(tmp_path)
    long = [f"app/{'x' * 190}{each}.py" for each in range(12)]
    for each in range(rollup_module.LISTED * rollup_module.PER_TEST):
        failure = _failure(f"tests/test_{each % rollup_module.LISTED:03}_{'y' * 180}.py::test_a", "missed")
        week.add(100 + each, _record(each, f"{each:040x}", "passes-wrongly", [failure], changed=long))
    rows = [
        f"| 2025-{month:02}-{day:02} | 0 | 0 | 0 | n/a | 0 | 0 | 0 |\n"
        for month in range(1, 13)
        for day in range(1, 10)
    ]
    body = week.body("".join(rows[: rollup_module.KEPT_WEEKS - 1]))
    assert len(body) <= rollup_module.MAX_BODY
    assert "more tests, in the artifacts" in body
    assert len(_lines(body, "| 202")) == rollup_module.KEPT_WEEKS
    assert week.body(body) == body


def test_what_an_artifact_says_is_set_as_code_and_cut_short(tmp_path: pathlib.Path) -> None:
    week = Week(tmp_path)
    hostile = _failure("tests/test_x.py::test_x[`@sstriker`\n# Heading]", "missed", link="`see` @sstriker")
    week.add(1, _record("12", _sha("e"), "passes-wrongly", [hostile], changed=["a`b", 7, "z" * 300]))
    body = week.body()
    assert "- `tests/test_x.py::test_x[@sstriker# Heading]`: 1 pushes of 1 pull requests" in body
    assert f"  - commit {'e' * 12} ([run](https://github.com/{REPOSITORY}/actions/runs/1)): `ab`, `{'z' * 200}`" in body
    assert "  - what links them: `see @sstriker`" in body
    assert "\n# Heading" not in body


def test_the_command_reads_the_list_of_runs_and_the_previous_body(
    week: Week, capsys: pytest.CaptureFixture[str]
) -> None:
    (week.root / "runs.tsv").write_text("\n".join(week.runs) + "\n")
    (week.root / "previous.md").write_text("| 2026-11-14 | 0 | 0 | 0 | n/a | 0 | 0 | 0 |\n")
    arguments = ["rollup", str(week.root), "--runs", str(week.root / "runs.tsv"), "--repo", REPOSITORY]
    audit_module.main([*arguments, "--previous", str(week.root / "previous.md"), "--until", UNTIL])
    assert capsys.readouterr().out == week.body("| 2026-11-14 | 0 | 0 | 0 | n/a | 0 | 0 | 0 |\n")
