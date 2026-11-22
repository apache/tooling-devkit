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

"""What the selection audit says of a pull request's failures (`scripts/ci/selection_audit.py`).

Its one wrong answer that matters is a miss that is not one, or a miss reported as something else: so each
outcome is asked for against a git repository and a junit report of its own, as CI hands them over. The
selection itself is the fast stage's, tested in test_fast_stage.py; here only how the audit reads it. The
weekly rollup is test_selection_rollup.py's.
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import types

import pytest

_CI = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ci"


def _load(name: str) -> types.ModuleType:
    """Load a module by path, since none is on the import path; each imports the ones before it by name."""
    spec = importlib.util.spec_from_file_location(name, _CI / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load("fast_stage_record")
_load("fast_stage")
audit_module = _load("selection_audit")

SUITE = {
    "app/roster/ledger.py": "X = 1\n",
    "app/models/agenda.py": "from app.roster.ledger import X\n",
    "app/mail.py": "",
    "tests/roster/test_ledger.py": "def test_a(): pass\n",
    "tests/test_books.py": "from app.roster.ledger import X\n\ndef test_a(): pass\n",
    "tests/test_agenda_view.py": "from app.models.agenda import Y\n\ndef test_a(): pass\n",
    "tests/test_notices.py": "def test_a():\n    assert 'sent' in mail.outbox\n",
    "tests/test_every_route.py": "def test_a(app):\n    assert app.url_map\n",
    "tests/test_plain.py": "def test_a(): pass\n",
}
"""A suite in small. A change to app/roster/ledger.py selects tests/test_every_route.py (tier 0),
tests/roster/test_ledger.py (its package) and tests/test_books.py (it imports the module), in that order."""

SECONDS = {"tests/test_plain.py": 20.0}
"""Each file takes a second but this one, so that the selection above is 3 s of 25, well inside the limit."""

ROUTE, LEDGER, BOOKS = "tests/test_every_route.py", "tests/roster/test_ledger.py", "tests/test_books.py"
VIEW, NOTICES, PLAIN = "tests/test_agenda_view.py", "tests/test_notices.py", "tests/test_plain.py"
LEDGER_CHANGE = {"app/roster/ledger.py": "X = 2\n"}


def _junit(results: dict[str, str], seconds: dict[str, float] | None = None) -> str:
    """A junit report as pytest writes it, for node ids and how each did: a file alone is a collection error."""
    bodies = {
        "passed": "",
        "failed": '<failure message="assert False"/>',
        "error": '<error message="collection failure"/>',
        "skipped": '<skipped message="no"/>',
    }
    cases = []
    for node, result in results.items():
        file, *inside = node.split("::")
        dotted = file.removesuffix(".py").replace("/", ".")
        classname, name = (".".join([dotted, *inside[:-1]]), inside[-1]) if inside else ("", dotted)
        time = (seconds or {}).get(file, 1.0)
        cases.append(f'<testcase classname="{classname}" name="{name}" time="{time}">{bodies[result]}</testcase>')
    return f'<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite>{"".join(cases)}</testsuite></testsuites>'


def _suite_junit(failed: dict[str, str], seconds: dict[str, float] | None = None) -> str:
    """The whole suite's report: every test file's test passed, but those given."""
    every = {f"{path}::test_a": "passed" for path in SUITE if path.startswith("tests/")}
    return _junit(every | failed, SECONDS | (seconds or {}))


def _git(root: pathlib.Path, *arguments: str) -> str:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    author = ["-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    finished = subprocess.run(
        ["git", *author, *arguments], cwd=root, env=environment, capture_output=True, text=True, check=True
    )
    return finished.stdout.strip()


def _commit(root: pathlib.Path, files: dict[str, str]) -> str:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", "x")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, SUITE)
    return tmp_path


def _report(repo: pathlib.Path, name: str, results: dict[str, str] | None) -> pathlib.Path | None:
    if results is None:
        return None
    (repo / name).write_text(_junit(results))
    return repo / name


def audit(
    repo: pathlib.Path,
    changed: dict[str, str],
    failed: dict[str, str],
    again: dict[str, str] | None,
    seconds: dict[str, float] | None = None,
    on_base: dict[str, str] | None = None,
) -> dict:
    """The audit of a commit changing `changed`, whose suite failed `failed`, whose failures did as `again`
    says when run again, and as `on_base` says on the base - None where nothing ran them."""
    base = _git(repo, "rev-parse", "HEAD")
    if changed:
        _commit(repo, changed)
    (repo / "junit.xml").write_text(_suite_junit(failed, seconds))
    reports = audit_module.Reports(
        repo / "junit.xml", _report(repo, "rerun.xml", again), _report(repo, "base.xml", on_base)
    )
    return audit_module.audit(repo, reports, base, "HEAD")


def outcomes(record: dict) -> dict[str, tuple[str, bool]]:
    return {each["test"]: (each["outcome"], each["selected"]) for each in record["failures"]}


# --- each failure --------------------------------------------------------------------------------------


def test_a_failure_in_a_selected_file_that_fails_again_is_caught(repo: pathlib.Path) -> None:
    failed = {f"{LEDGER}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed)
    assert list(record["selection"]) == [ROUTE, LEDGER, BOOKS]
    assert outcomes(record) == {f"{LEDGER}::test_a": ("caught", True)}
    assert record["verdict"] == "fails"
    assert record["counts"]["caught"] == 1 and record["counts"]["missed"] == 0


def test_a_failure_in_a_file_not_selected_that_fails_again_is_missed(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed)
    assert outcomes(record) == {f"{PLAIN}::test_a": ("missed", False)}
    assert record["verdict"] == "passes-wrongly"
    assert record["failures"][0]["link"] is None


def test_one_caught_failure_makes_the_stage_fail_whatever_else_it_missed(repo: pathlib.Path) -> None:
    failed = {f"{LEDGER}::test_a": "failed", f"{PLAIN}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed)
    assert outcomes(record) == {f"{LEDGER}::test_a": ("caught", True), f"{PLAIN}::test_a": ("missed", False)}
    assert record["verdict"] == "fails"


def test_a_miss_says_which_import_ties_the_test_to_the_change(repo: pathlib.Path) -> None:
    failed = {f"{VIEW}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed)
    assert outcomes(record) == {f"{VIEW}::test_a": ("missed", False)}
    assert record["failures"][0]["link"] == "it imports app/models/agenda.py, which imports app/roster/ledger.py"


def test_a_miss_says_when_the_test_names_the_changed_module(repo: pathlib.Path) -> None:
    failed = {f"{NOTICES}::test_a": "failed"}
    record = audit(repo, {"app/mail.py": "SENT = []\n"}, failed, failed)
    assert outcomes(record) == {f"{NOTICES}::test_a": ("missed", False)}
    assert record["failures"][0]["link"] == "it names `mail`, the module of app/mail.py"


def test_each_miss_says_its_own_link(repo: pathlib.Path) -> None:
    failed = {f"{VIEW}::test_a": "failed", f"{NOTICES}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE | {"app/mail.py": "SENT = []\n"}, failed, failed)
    assert {each["test"]: each["link"] for each in record["failures"]} == {
        f"{VIEW}::test_a": "it imports app/models/agenda.py, which imports app/roster/ledger.py",
        f"{NOTICES}::test_a": "it names `mail`, the module of app/mail.py",
    }


def test_a_change_that_reaches_every_test_sends_its_failures_to_the_full_suite(repo: pathlib.Path) -> None:
    failed = {f"{ROUTE}::test_a": "failed", f"{PLAIN}::test_a": "failed"}
    record = audit(repo, {"pyproject.toml": "[project]\n"}, failed, failed)
    assert record["triggered"] and not record["capped"]
    assert outcomes(record) == {f"{ROUTE}::test_a": ("sent", True), f"{PLAIN}::test_a": ("sent", False)}
    assert record["verdict"] == "fails"
    assert record["counts"]["sent"] == 2 and record["counts"]["missed"] == 0


def test_a_change_sent_to_the_full_suite_with_nothing_selected_failing_is_not_passed(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a": "failed"}
    record = audit(repo, {"pyproject.toml": "[project]\n"}, failed, failed)
    assert outcomes(record) == {f"{PLAIN}::test_a": ("sent", False)}
    assert record["verdict"] == "needs-the-suite"


def test_a_selection_past_the_limit_is_sent_and_says_whether_the_failure_was_in_what_it_still_ran(
    repo: pathlib.Path,
) -> None:
    """tests/test_books.py is chosen last and costs 50 s of 74: the limit drops it, and keeps the rest."""
    failed = {f"{LEDGER}::test_a": "failed", f"{BOOKS}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed, {BOOKS: 50.0})
    assert record["capped"] and not record["triggered"]
    assert list(record["selection"]) == [ROUTE, LEDGER]
    assert outcomes(record) == {f"{LEDGER}::test_a": ("sent", True), f"{BOOKS}::test_a": ("sent", False)}
    assert record["verdict"] == "fails"


def test_a_failure_the_limit_dropped_is_sent_not_missed(repo: pathlib.Path) -> None:
    failed = {f"{BOOKS}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed, {BOOKS: 50.0})
    assert outcomes(record) == {f"{BOOKS}::test_a": ("sent", False)}
    assert record["verdict"] == "needs-the-suite"


# --- run again -----------------------------------------------------------------------------------------


def test_a_failure_that_passes_when_run_again_is_a_flake_and_never_a_miss(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a": "failed", f"{LEDGER}::test_a": "failed"}
    again = {f"{PLAIN}::test_a": "passed", f"{LEDGER}::test_a": "passed"}
    record = audit(repo, LEDGER_CHANGE, failed, again)
    assert outcomes(record) == {f"{PLAIN}::test_a": ("flake", False), f"{LEDGER}::test_a": ("flake", True)}
    assert record["counts"] | {"flake": 0} == dict.fromkeys(audit_module.OUTCOMES, 0)
    assert record["verdict"] == "clean"


def test_a_flake_in_a_change_sent_to_the_full_suite_is_a_flake(repo: pathlib.Path) -> None:
    record = audit(
        repo, {"pyproject.toml": "[project]\n"}, {f"{PLAIN}::test_a": "failed"}, {f"{PLAIN}::test_a": "passed"}
    )
    assert outcomes(record) == {f"{PLAIN}::test_a": ("flake", False)}


def test_a_failure_nothing_ran_again_is_unconfirmed_and_never_a_miss(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a": "failed"}
    record = audit(repo, {"app/mail.py": "X = 1\n"}, failed, None)
    assert outcomes(record) == {f"{PLAIN}::test_a": ("unconfirmed", False)}
    assert record["verdict"] == "unanswered"


def test_a_failure_the_re_run_did_not_report_is_unconfirmed(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a": "failed", f"{BOOKS}::test_a": "failed"}
    record = audit(repo, {"app/mail.py": "X = 1\n"}, failed, {f"{BOOKS}::test_a": "skipped"})
    assert outcomes(record) == {f"{PLAIN}::test_a": ("unconfirmed", False), f"{BOOKS}::test_a": ("unconfirmed", False)}


def test_a_test_the_re_run_left_out_is_not_judged_by_another_test_of_its_file(repo: pathlib.Path) -> None:
    record = audit(repo, LEDGER_CHANGE, {f"{PLAIN}::test_a": "failed"}, {f"{PLAIN}::test_b": "passed"})
    assert outcomes(record) == {f"{PLAIN}::test_a": ("unconfirmed", False)}


@pytest.mark.parametrize("written", ["", "<testsuites><testsuite/></testsuites>", "<testsuites><testcase"])
def test_a_re_run_report_that_says_nothing_is_no_re_run(repo: pathlib.Path, written: str) -> None:
    """Absent, empty, or broken: an id pytest cannot find makes it run nothing at all, and say so in this way."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "junit.xml").write_text(_suite_junit({f"{PLAIN}::test_a": "failed"}))
    if written:
        (repo / "rerun.xml").write_text(written)
    record = audit_module.audit(repo, audit_module.Reports(repo / "junit.xml", repo / "rerun.xml"), base, "HEAD")
    assert outcomes(record) == {f"{PLAIN}::test_a": ("unconfirmed", False)}
    assert record["verdict"] == "unanswered"


def test_a_file_that_failed_to_collect_is_a_failure_of_that_file(repo: pathlib.Path) -> None:
    failed = {LEDGER: "error", PLAIN: "error"}
    record = audit(repo, LEDGER_CHANGE, failed, failed)
    assert outcomes(record) == {LEDGER: ("caught", True), PLAIN: ("missed", False)}


def test_a_file_that_failed_to_collect_and_then_ran_is_judged_by_its_tests(repo: pathlib.Path) -> None:
    failed = {LEDGER: "error", PLAIN: "error"}
    again = {f"{LEDGER}::test_a": "failed", f"{PLAIN}::test_a": "passed", f"{BOOKS}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, again)
    assert outcomes(record) == {LEDGER: ("caught", True), PLAIN: ("flake", False)}


def test_a_file_that_failed_to_collect_and_then_only_skipped_is_unconfirmed(repo: pathlib.Path) -> None:
    record = audit(repo, LEDGER_CHANGE, {PLAIN: "error"}, {f"{PLAIN}::test_a": "skipped"})
    assert outcomes(record) == {PLAIN: ("unconfirmed", False)}


@pytest.mark.parametrize("again", [None, {"tests/roster": "passed"}, {"tests/roster": "error"}])
def test_an_error_no_test_file_is_named_for_is_unplaced_and_leaves_the_run_unanswered(
    repo: pathlib.Path, again: dict[str, str] | None
) -> None:
    record = audit(repo, LEDGER_CHANGE, {"tests/roster": "error"}, again)
    assert outcomes(record) == {"tests.roster": ("unplaced", False)}
    assert record["verdict"] == "unanswered"


def test_an_unplaced_error_beside_a_miss_leaves_the_run_unanswered(repo: pathlib.Path) -> None:
    """A conftest of the selected package that does not import fails every test the stage would run there."""
    failed = {f"{PLAIN}::test_a": "failed", "tests/roster": "error"}
    record = audit(repo, LEDGER_CHANGE, failed, failed)
    assert outcomes(record) == {f"{PLAIN}::test_a": ("missed", False), "tests.roster": ("unplaced", False)}
    assert record["verdict"] == "unanswered"


def test_a_selected_failure_not_run_again_beside_a_miss_leaves_the_run_unanswered(repo: pathlib.Path) -> None:
    """Had it failed again, the stage would have failed: nobody can tell that it would have passed."""
    failed = {f"{LEDGER}::test_a": "failed", f"{PLAIN}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, {f"{PLAIN}::test_a": "failed"})
    assert outcomes(record) == {f"{LEDGER}::test_a": ("unconfirmed", True), f"{PLAIN}::test_a": ("missed", False)}
    assert record["verdict"] == "unanswered"


def test_a_failure_not_run_again_outside_the_selection_leaves_a_miss_a_miss(repo: pathlib.Path) -> None:
    """Whatever it did again, the stage would not have run it: the miss beside it decides."""
    failed = {f"{VIEW}::test_a": "failed", f"{PLAIN}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, {f"{PLAIN}::test_a": "failed"})
    assert outcomes(record) == {f"{VIEW}::test_a": ("unconfirmed", False), f"{PLAIN}::test_a": ("missed", False)}
    assert record["verdict"] == "passes-wrongly"


# --- the base ------------------------------------------------------------------------------------------


def test_a_miss_that_fails_on_the_base_too_is_inherited(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed, on_base=failed)
    assert outcomes(record) == {f"{PLAIN}::test_a": ("inherited", False)}
    assert record["verdict"] == "inherited"
    assert record["counts"]["missed"] == 0 and record["counts"]["inherited"] == 1


def test_a_miss_that_passes_on_the_base_stays_a_miss(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed, on_base={f"{PLAIN}::test_a": "passed"})
    assert outcomes(record) == {f"{PLAIN}::test_a": ("missed", False)}
    assert record["verdict"] == "passes-wrongly"


def test_the_base_decides_nothing_but_a_miss(repo: pathlib.Path) -> None:
    failed = {f"{LEDGER}::test_a": "failed", f"{PLAIN}::test_a": "failed"}
    record = audit(repo, LEDGER_CHANGE, failed, failed, on_base=failed)
    assert outcomes(record) == {f"{LEDGER}::test_a": ("caught", True), f"{PLAIN}::test_a": ("inherited", False)}
    assert record["verdict"] == "fails"


# --- the change ----------------------------------------------------------------------------------------


def test_a_suite_with_no_failures_has_nothing_to_count(repo: pathlib.Path) -> None:
    record = audit(repo, LEDGER_CHANGE, {}, None)
    assert record["failures"] == []
    assert record["counts"] == dict.fromkeys(audit_module.OUTCOMES, 0)
    assert record["verdict"] == "clean"
    assert "No test failed." in audit_module.summary(record)


def test_an_empty_change_selects_tier_0_alone(repo: pathlib.Path) -> None:
    failed = {f"{ROUTE}::test_a": "failed", f"{PLAIN}::test_a": "failed"}
    record = audit(repo, {}, failed, failed)
    assert record["changed"] == []
    assert list(record["selection"]) == [ROUTE]
    assert outcomes(record) == {f"{ROUTE}::test_a": ("caught", True), f"{PLAIN}::test_a": ("missed", False)}


def test_a_selection_of_nothing_is_not_a_pass(repo: pathlib.Path) -> None:
    _commit(repo, {ROUTE: "def test_a(): pass\n"})
    failed = {f"{PLAIN}::test_a": "failed"}
    record = audit(repo, {}, failed, failed)
    assert record["selection"] == {}
    assert record["verdict"] == "needs-the-suite"


def test_the_change_is_measured_from_where_the_branch_meets_its_base(repo: pathlib.Path) -> None:
    fork = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "branch")
    _commit(repo, LEDGER_CHANGE)
    _git(repo, "checkout", "-q", "main")
    _commit(repo, {"app/mail.py": "X = 1\n"})
    (repo / "junit.xml").write_text(_suite_junit({}))
    record = audit_module.audit(repo, audit_module.Reports(repo / "junit.xml"), "main", "branch")
    assert record["merge_base"] == fork
    assert record["head"] == _git(repo, "rev-parse", "branch")
    assert record["changed"] == ["app/roster/ledger.py"]


def test_a_rename_changes_both_names(repo: pathlib.Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "mv", "app/mail.py", "app/post.py")
    _git(repo, "commit", "-q", "-m", "rename")
    (repo / "junit.xml").write_text(_suite_junit({}))
    record = audit_module.audit(repo, audit_module.Reports(repo / "junit.xml"), base, "HEAD")
    assert record["changed"] == ["app/mail.py", "app/post.py"]


def test_a_ref_git_cannot_read_is_no_audit(repo: pathlib.Path) -> None:
    (repo / "junit.xml").write_text(_suite_junit({}))
    with pytest.raises(audit_module.UnauditedError, match="merge-base"):
        audit_module.audit(repo, audit_module.Reports(repo / "junit.xml"), "no-such-ref", "HEAD")


# --- node ids --------------------------------------------------------------------------------------------


def test_node_ids_are_read_back_as_pytest_writes_them(repo: pathlib.Path) -> None:
    (repo / "junit.xml").write_text(
        _junit({f"{LEDGER}::TestThem::test_b[a b]": "failed", PLAIN: "error", f"{BOOKS}::test_a": "skipped"})
    )
    cases = audit_module.read_cases(repo, repo / "junit.xml")
    assert [(case.test, case.file, case.failed) for case in cases] == [
        (f"{LEDGER}::TestThem::test_b[a b]", LEDGER, True),
        (PLAIN, PLAIN, True),
        (f"{BOOKS}::test_a", BOOKS, False),
    ]


def test_what_is_run_again_leaves_out_an_error_no_file_holds(repo: pathlib.Path) -> None:
    """pytest cannot find `tests.roster`, and one id it cannot find makes it run none of the others."""
    (repo / "junit.xml").write_text(_junit({"tests/roster": "error", PLAIN: "error", f"{BOOKS}::test_a": "failed"}))
    audit_module.main(["failed", "--junit", str(repo / "junit.xml"), "--root", str(repo), "--out", str(repo / "ids")])
    assert (repo / "ids").read_text().splitlines() == [PLAIN, f"{BOOKS}::test_a"]


def _pytest(cwd: pathlib.Path, junit: str, *arguments: str) -> None:
    command = [sys.executable, "-m", "pytest", "-q", "-n", "2", "-p", "no:cacheprovider", f"--junitxml={junit}"]
    subprocess.run([*command, *arguments], cwd=cwd, capture_output=True, check=False)


REAL_SUITES = {
    "tests and parameters": (
        {
            "tests/test_real.py": "import pytest\n\nclass TestThem:\n    def test_in_a_class(self):\n"
            "        assert False\n\n@pytest.mark.parametrize('value', ['a b', 'c'])\n"
            "def test_param(value):\n    assert value != 'a b'\n",
        },
        ["tests/test_real.py::TestThem::test_in_a_class", "tests/test_real.py::test_param[a b]"],
    ),
    "a file and a package that do not collect": (
        {
            "tests/sub/__init__.py": "",
            "tests/sub/conftest.py": "import no_such_module\n",
            "tests/sub/test_in_sub.py": "def test_a(): pass\n",
            "tests/test_broken.py": "import no_such_module_either\n",
            "tests/test_ok.py": "def test_a(): pass\n",
        },
        ["tests/test_broken.py"],
    ),
}


@pytest.mark.parametrize("files, ids", REAL_SUITES.values(), ids=REAL_SUITES.keys())
def test_what_failed_is_run_again_by_the_node_ids_pytest_gave_it(
    tmp_path: pathlib.Path, files: dict[str, str], ids: list[str]
) -> None:
    """From real pytest runs over xdist, as CI's: the ids `failed` writes are what pytest @file runs, and they
    fail again under the same ids."""
    for path, text in (files | {"pytest.ini": "[pytest]\n"}).items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    _pytest(tmp_path, "suite.xml", "tests")
    audit_module.main(
        ["failed", "--junit", str(tmp_path / "suite.xml"), "--root", str(tmp_path), "--out", str(tmp_path / "ids")]
    )
    assert sorted((tmp_path / "ids").read_text().splitlines()) == ids  # xdist reports in no fixed order
    _pytest(tmp_path, "rerun.xml", "@ids")
    rerun = audit_module.read_cases(tmp_path, tmp_path / "rerun.xml")
    assert sorted(case.test for case in audit_module.failing(rerun)) == ids


def test_the_misses_files_are_written_once_each_to_run_on_the_base(repo: pathlib.Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, LEDGER_CHANGE)
    failed = {f"{PLAIN}::test_a": "failed", f"{PLAIN}::test_b": "failed", f"{LEDGER}::test_a": "failed"}
    failed |= {f"{VIEW}::test_a": "failed"}
    (repo / "junit.xml").write_text(_suite_junit(failed))
    (repo / "rerun.xml").write_text(_junit(failed | {f"{VIEW}::test_a": "passed"}))
    arguments = ["missed", "--junit", str(repo / "junit.xml"), "--rerun", str(repo / "rerun.xml"), "--base", base]
    audit_module.main([*arguments, "--root", str(repo), "--out", str(repo / "missed")])
    assert (repo / "missed").read_text().splitlines() == [PLAIN]


# --- the job summary and the record ------------------------------------------------------------------


def test_the_summary_gives_the_verdict_each_failure_and_what_links_a_miss(repo: pathlib.Path) -> None:
    failed = {f"{VIEW}::test_a": "failed", f"{LEDGER}::test_a": "failed"}
    said = audit_module.summary(audit(repo, LEDGER_CHANGE, failed, failed))
    assert f"**{audit_module.VERDICTS['fails']}.**" in said
    assert f"| `{LEDGER}::test_a` | caught | from app/roster/ledger.py |" in said
    assert f"| `{VIEW}::test_a` | missed | - |" in said
    assert f"Missed `{VIEW}::test_a`: it imports app/models/agenda.py, which imports app/roster/ledger.py." in said
    assert "It selects 3 of 6 test files, 12% of the suite's test time." in said


def test_the_summary_says_why_a_change_is_sent_and_whether_the_failure_was_in_what_ran(repo: pathlib.Path) -> None:
    failed = {f"{LEDGER}::test_a": "failed", f"{BOOKS}::test_a": "failed"}
    said = audit_module.summary(audit(repo, LEDGER_CHANGE, failed, failed, {BOOKS: 50.0}))
    assert "- the selection is 70% of the suite, past 40%: it runs 3%" in said
    assert f"| `{LEDGER}::test_a` | sent, in what the stage still ran |" in said
    assert f"| `{BOOKS}::test_a` | sent, not in what the stage ran | - |" in said


def test_the_summary_keeps_a_table_cell_whole_and_names_an_inherited_failure(repo: pathlib.Path) -> None:
    failed = {f"{PLAIN}::test_a[x|y]": "failed"}
    said = audit_module.summary(audit(repo, LEDGER_CHANGE, failed, failed, on_base=failed))
    assert f"| `{PLAIN}::test_a[x\\|y]` | inherited: it fails on the base too | - |" in said


def _command(repo: pathlib.Path, *more: str) -> list[str]:
    arguments = ["audit", "--junit", str(repo / "junit.xml"), "--rerun", str(repo / "rerun.xml")]
    arguments += ["--base", _git(repo, "rev-parse", "HEAD~1"), "--root", str(repo)]
    return [
        *arguments,
        "--out",
        str(repo / "out" / "selection-audit.json"),
        "--pr",
        "12",
        "--pr-head",
        "abc1234",
        *more,
    ]


def test_the_command_writes_the_record_and_adds_to_the_job_summary(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit(repo, LEDGER_CHANGE)
    failed = {f"{PLAIN}::test_a": "failed"}
    (repo / "junit.xml").write_text(_suite_junit(failed))
    (repo / "rerun.xml").write_text(_junit(failed))
    (repo / "summary.md").write_text("before\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(repo / "summary.md"))
    run = "https://github.com/apache/tooling-agenda/actions/runs/7"
    assert audit_module.main(_command(repo, "--run", run)) == 0
    record = json.loads((repo / "out" / "selection-audit.json").read_text())
    assert (record["pr"], record["pr_head"], record["run"], record["verdict"]) == (12, "abc1234", run, "passes-wrongly")
    assert record["audited"] is True
    assert (repo / "summary.md").read_text().startswith("before\n## Would the fast stage have caught it?")


@pytest.mark.parametrize(
    "junit, why",
    [
        (None, "the suite wrote no junit report"),
        ("<testsuites><testcase", "the suite's junit report does not parse: "),
    ],
)
def test_a_run_with_no_report_to_read_keeps_a_record_that_says_so(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch, junit: str | None, why: str
) -> None:
    _commit(repo, LEDGER_CHANGE)
    if junit is not None:
        (repo / "junit.xml").write_text(junit)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(repo / "summary.md"))
    assert audit_module.main(_command(repo)) == 0
    record = json.loads((repo / "out" / "selection-audit.json").read_text())
    assert record["audited"] is False and record["why"].startswith(why)
    assert (record["pr"], record["pr_head"]) == (12, "abc1234")
    assert f"This run could not be audited: {why}" in (repo / "summary.md").read_text()


def test_a_base_git_cannot_find_keeps_a_record_that_says_so(repo: pathlib.Path) -> None:
    (repo / "junit.xml").write_text(_suite_junit({}))
    arguments = ["audit", "--junit", str(repo / "junit.xml"), "--base", "no-such-ref", "--root", str(repo)]
    assert audit_module.main([*arguments, "--out", str(repo / "out.json")]) == 0
    record = json.loads((repo / "out.json").read_text())
    assert record["audited"] is False and "merge-base" in record["why"]
