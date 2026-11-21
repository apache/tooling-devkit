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

"""What the fast local stage selects, and from which base (`scripts/ci/fast_stage.py`).

A selection that leaves out the test a change breaks reads as a pass, which is the failure that
matters; one that takes too much only costs time. So each rule is asked both ways, against a small
tree of its own, and the base against a git repository of its own. Nothing here needs the suite's
fixtures, so the file also runs on its own, outside the checkout.
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
    """Load a half by path, since neither is on the import path; the record half first, because the stage
    imports it by name."""
    spec = importlib.util.spec_from_file_location(name, _CI / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


kept = _load("fast_stage_record")
fast_stage = _load("fast_stage")

TESTS = {
    "tests/test_roster_service.py": "def test_a(): pass\n",
    "tests/test_roster_views.py": "def test_a(): pass\n",
    "tests/roster/test_events.py": "def test_a(): pass\n",
    "tests/test_mail.py": "def test_a(): pass\n",
    "tests/actions/test_digest_mail.py": "def test_a(): pass\n",
    "tests/api/conftest.py": "",
    "tests/api/test_secretary_actions.py": "def test_a(): pass\n",
    "tests/api/test_meetings.py": "def test_a(): pass\n",
    "tests/api/test_email_templates.py": "def test_a(): pass\n",
    "tests/api/test_ping.py": "CLIENT = ROOT / 'assets' / 'src' / 'js' / 'libs' / 'server.svelte.ts'\n",
    "tests/client/test_documentation.py": "def test_a(): pass\n",
    "tests/client/test_page_shell.py": "def test_a(page):\n    assert page.template == 'committee.html'\n",
    "tests/client/test_icons.py": "IMAGES = ROOT / 'assets' / 'src' / 'img'\n",
    "tests/models/test_agenda_model.py": "def test_a(): pass\n",
    "tests/md/test_pages.py": "def test_a(): pass\n",
    "tests/test_calendar.py": "from app.models import (\n    agenda,\n    meeting_start,\n)\n",
    "tests/test_slug_links.py": "import app.slugs\n",
    "tests/test_quality_ratchet.py": "def test_a(): pass\n",
    "tests/test_plain.py": "def test_a(): pass\n",
    "tests/whimsy.py": "ANCHORS = ()\n",
    "tests/test_anchors.py": "from tests.whimsy import ANCHORS\n\ndef test_a(): pass\n",
    "tests/test_import_boundaries.py": "import grimp\n\ndef test_a(): pass\n",
    "tests/test_web_admin.py": "def test_a(app):\n    assert app.url_map\n",
    "tests/test_routes_cost.py": "def test_a(app):\n    assert app.url_map\n",
    "tests/test_element_snapshot.py": "def test_a(snapshot): pass\n",
    "tests/test_workflows.py": "def test_a(root):\n    assert list(root.glob('*.yml'))\n",
    "tests/test_directory.py": "def entry(): pass\n",
    "tests/test_drift_diff.py": "from tests.test_directory import entry\n",
    "tests/test_orders.py": "from app.models.agenda import Order\n",
    "tests/test_reports.py": "from app.models.agenda import R\n",
    "tests/test_sections.py": "from app.models.agenda import (\n    Other,\n    SectionType,\n)\n",
}
PACKAGE = "from .items import Order, Report as R\nfrom app.models.agenda.section_type import (\n    SectionType,\n)\n"
"""A suite in small: three tier 0 files that are cheap, one that is not, and an expensive snapshot."""

DURATIONS = {path: 1.0 for path in TESTS if "/test_" in path} | {
    "tests/test_routes_cost.py": 40.0,
    "tests/test_element_snapshot.py": 40.0,
}
TIER0 = [
    "tests/test_element_snapshot.py",
    "tests/test_import_boundaries.py",
    "tests/test_web_admin.py",
    "tests/test_workflows.py",
]


def _write(root: pathlib.Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)


@pytest.fixture
def tree(tmp_path: pathlib.Path) -> pathlib.Path:
    _write(tmp_path, TESTS | {"app/models/agenda/__init__.py": PACKAGE})
    return tmp_path


def selected(root: pathlib.Path, *changed: str, failed: frozenset[str] = frozenset()) -> dict[str, list[str]]:
    plan = fast_stage.make_plan(root, set(changed), DURATIONS, set(failed), limit=1.0)
    assert not plan.reasons
    return plan.rules


def by_path(root: pathlib.Path, *changed: str) -> set[str]:
    """What the path rule alone selects: the selection without tier 0."""
    return set(selected(root, *changed)) - set(TIER0)


# --- the path rule ----------------------------------------------------------------------------


def test_a_module_selects_the_tests_named_for_it_and_its_package(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/roster/service.py") == {
        "tests/test_roster_service.py",
        "tests/test_roster_views.py",
        "tests/roster/test_events.py",
    }


def test_a_module_selects_a_test_with_its_name_after_an_underscore(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/mail.py") == {"tests/test_mail.py", "tests/actions/test_digest_mail.py"}


@pytest.mark.parametrize("package", ["actions", "api", "md", "models"])
def test_a_module_in_a_broad_package_selects_its_own_tests_and_not_the_package(
    tree: pathlib.Path, package: str
) -> None:
    assert by_path(tree, f"app/{package}/unnamed.py") == set()


@pytest.mark.parametrize("name", ["__init__", "models", "routes", "service", "tables"])
def test_a_module_named_for_its_role_is_named_by_its_directory(tree: pathlib.Path, name: str) -> None:
    assert by_path(tree, f"app/api/meetings/{name}.py") == {"tests/api/test_meetings.py"}


def test_a_module_selects_the_tests_that_import_it(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/models/meeting_start.py") == {"tests/test_calendar.py"}
    assert by_path(tree, "app/slugs.py") == {"tests/test_slug_links.py"}
    assert by_path(tree, "app/models/__init__.py") == set()  # a package: everybody imports from it


def test_a_changed_test_selects_itself_and_a_deleted_one_nothing(tree: pathlib.Path) -> None:
    assert by_path(tree, "tests/test_plain.py") == {"tests/test_plain.py"}
    assert by_path(tree, "tests/test_gone.py") == set()


def test_a_changed_test_also_selects_the_tests_that_import_from_it(tree: pathlib.Path) -> None:
    assert by_path(tree, "tests/test_directory.py") == {"tests/test_directory.py", "tests/test_drift_diff.py"}


def test_a_module_reached_over_http_selects_the_tests_of_its_package(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/client/installed_app.py") == {
        "tests/client/test_documentation.py",
        "tests/client/test_page_shell.py",
        "tests/client/test_icons.py",
    }


def test_a_module_selects_the_tests_that_import_what_its_package_re_exports(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/models/agenda/items.py") == {"tests/test_orders.py", "tests/test_reports.py"}
    assert by_path(tree, "app/models/agenda/section_type.py") == {"tests/test_sections.py"}


def test_a_script_selects_the_tests_named_for_it_and_those_that_name_it(tree: pathlib.Path) -> None:
    _write(tree, {"tests/test_index.py": "SCRIPT = ROOT / 'scripts' / 'index-minutes.py'\n"})
    assert by_path(tree, "scripts/ci/quality.py") == {"tests/test_quality_ratchet.py"}
    assert by_path(tree, "scripts/index-minutes.py") == {"tests/test_index.py"}


def test_a_page_of_the_documentation_selects_the_documentation_tests(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/md/documentation/board-chair.md") == {"tests/client/test_documentation.py"}


def test_a_template_selects_the_tests_that_name_it_and_those_named_for_its_directory(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/client/templates/committee.html") == {
        "tests/client/test_page_shell.py",
        "tests/client/test_documentation.py",
        "tests/client/test_icons.py",
        "tests/api/test_email_templates.py",
    }


def test_a_data_file_selects_the_tests_of_its_package(tree: pathlib.Path) -> None:
    assert by_path(tree, "app/roster/data/aliases.yaml") == {
        "tests/test_roster_service.py",
        "tests/test_roster_views.py",
        "tests/roster/test_events.py",
    }


def test_a_frontend_file_selects_the_tests_that_name_it_or_its_directory(tree: pathlib.Path) -> None:
    assert by_path(tree, "assets/src/js/libs/server.svelte.ts") == {"tests/api/test_ping.py"}
    assert by_path(tree, "assets/src/img/icon-192.png") == {"tests/client/test_icons.py"}


def test_what_no_test_reads_selects_nothing_by_path(tree: pathlib.Path) -> None:
    assert by_path(tree, "docs/design-book.html", "assets/src/css/x.ts", "Makefile") == set()


def test_a_conftest_selects_its_directory(tree: pathlib.Path) -> None:
    assert by_path(tree, "tests/api/conftest.py") == {
        "tests/api/test_secretary_actions.py",
        "tests/api/test_meetings.py",
        "tests/api/test_email_templates.py",
        "tests/api/test_ping.py",
    }


def test_a_helper_at_the_top_selects_the_tests_that_import_it(tree: pathlib.Path) -> None:
    assert by_path(tree, "tests/whimsy.py") == {"tests/test_anchors.py"}


def test_each_file_says_which_rule_chose_it(tree: pathlib.Path) -> None:
    rules = selected(tree, "app/mail.py", "tests/test_mail.py")
    assert rules["tests/test_mail.py"] == ["from app/mail.py", "changed"]
    assert rules["tests/test_web_admin.py"] == ["tier 0"]


def test_the_path_rule_trusts_name_and_place_before_text_and_imports(tree: pathlib.Path) -> None:
    """The limit drops the last-chosen first, so what reaches furthest is what goes first."""
    _write(tree, {"tests/test_sender.py": "SOURCE = 'mail.py'\n"})
    rules = selected(tree, "app/mail.py", "app/models/meeting_start.py")
    assert list(rules)[len(TIER0) :] == [
        "tests/actions/test_digest_mail.py",
        "tests/test_mail.py",
        "tests/test_sender.py",
        "tests/test_calendar.py",
    ]
    assert rules["tests/test_sender.py"] == ["names app/mail.py"]
    assert rules["tests/test_calendar.py"] == ["imports app/models/meeting_start.py"]


# --- tier 0 -----------------------------------------------------------------------------------


def test_tier0_is_the_cheap_list_checking_tests_and_every_snapshot(tree: pathlib.Path) -> None:
    assert [path for path, rules in selected(tree).items() if "tier 0" in rules] == TIER0


def test_a_new_list_checking_test_joins_tier0_by_itself(tree: pathlib.Path) -> None:
    _write(tree, {"tests/test_every_table.py": "def test_a(db):\n    assert db.metadata.tables\n"})
    assert "tests/test_every_table.py" in selected(tree)


# --- failed last -----------------------------------------------------------------------------


def test_what_failed_last_runs_first_then_tier0_then_the_path_rule(tree: pathlib.Path) -> None:
    rules = selected(tree, "app/mail.py", failed=frozenset({"tests/test_plain.py"}))
    assert next(iter(rules)) == "tests/test_plain.py"
    assert list(rules)[1 : 1 + len(TIER0)] == TIER0
    assert rules["tests/test_plain.py"] == ["failed last"]


def test_a_file_that_failed_and_is_gone_is_not_asked_for(tree: pathlib.Path) -> None:
    assert "tests/test_gone.py" not in selected(tree, failed=frozenset({"tests/test_gone.py"}))


def test_failed_last_is_what_pytests_cache_says(tree: pathlib.Path) -> None:
    lastfailed = {"tests/test_mail.py::test_a[1]": True, "tests/api/test_meetings.py": True}
    _write(tree, {fast_stage.LASTFAILED: json.dumps(lastfailed)})
    assert fast_stage.failed_before(tree) == {"tests/test_mail.py", "tests/api/test_meetings.py"}


def test_nothing_recorded_is_nothing_failed(tree: pathlib.Path) -> None:
    assert fast_stage.failed_before(tree) == set()


# --- what needs the whole suite ---------------------------------------------------------------

EVERY_TEST = {
    "pyproject.toml": "pyproject.toml",
    "uv.lock": "uv.lock",
    "requirements.txt": "requirements.txt",
    ".python-version": ".python-version",
    "tests/__init__.py": "tests/__init__.py",
    "tests/conftest.py": "tests/conftest.py",
    "tests/test-config.yaml": "tests/test-config.yaml",
    "tests/data/**": "tests/data/wc/board/agenda.txt",
    "tests/behaviour/**": "tests/behaviour/world.py",
    "schema/**": "schema/board-records-2.json",
    "app/__init__.py": "app/__init__.py",
    "app/webapp.py": "app/webapp.py",
    "server.py": "server.py",
    "app/*/migrations/**": "app/roster/migrations/versions/0007_x.py",
}
"""A path each glob of `FULL_WHEN` is there for."""


def test_every_trigger_is_asked_for() -> None:
    assert set(EVERY_TEST) == set(fast_stage.FULL_WHEN)


@pytest.mark.parametrize("path", sorted(EVERY_TEST.values()))
def test_a_change_that_reaches_every_test_needs_the_whole_suite_and_still_selects(
    tree: pathlib.Path, path: str
) -> None:
    plan = fast_stage.make_plan(tree, {path, "app/mail.py"}, DURATIONS, set(), limit=1.0)
    assert [reason.split(":")[0] for reason in plan.reasons] == [path]
    assert "tests/test_mail.py" in plan.rules


def test_a_module_tests_conftest_imports_reaches_every_test(tree: pathlib.Path) -> None:
    conftest = "from app import config as c\nfrom app.db.service import store\nfrom app.directory import audit\n"
    conftest += "def fixture():\n    from app.models import meeting_start\n"
    _write(tree, {"tests/conftest.py": conftest, "app/config.py": "", "app/models/meeting_start.py": ""})
    _write(tree, {"app/models/other.py": "", "app/db/service.py": ""})
    _write(tree, {"app/directory/__init__.py": "", "app/directory/audit.py": ""})
    changed = {"app/config.py", "app/models/meeting_start.py", "app/db/service.py", "app/models/other.py"}
    changed |= {"app/directory/__init__.py"}
    reasons = fast_stage.full_run_reasons(tree, changed)
    assert [reason.split(":")[0] for reason in reasons] == [
        "app/config.py",
        "app/db/service.py",
        "app/directory/__init__.py",
        "app/models/meeting_start.py",
    ]
    assert "imported by tests/conftest.py" in reasons[0]


@pytest.mark.parametrize(
    "path",
    [
        "app/roster/service.py",
        "app/md/documentation/x.md",
        "app/client/templates/page.html",
        "app/client/static/css/app.css",
        "app/models/data/aliases.yaml",
        "app/db/alembic.ini",
        "docs/x.md",
        "assets/package.json",
        "Makefile",
    ],
)
def test_a_change_a_rule_maps_runs_a_selection(tree: pathlib.Path, path: str) -> None:
    assert not fast_stage.make_plan(tree, {path}, DURATIONS, set(), limit=1.0).reasons


def test_a_selection_past_the_limit_runs_what_fits_in_order_and_needs_the_whole_suite(tree: pathlib.Path) -> None:
    plan = fast_stage.make_plan(tree, {"app/roster/service.py"}, DURATIONS, set(), limit=0.5)
    assert not plan.reasons
    share, whole = plan.share, list(plan.rules)
    over = fast_stage.make_plan(tree, {"app/roster/service.py"}, DURATIONS, set(), limit=share - 0.01)
    assert over.share <= share - 0.01
    assert list(over.rules) == whole[: len(over.rules)]
    one_more = sum(over.seconds[path] for path in whole[: len(over.rules) + 1]) / sum(over.seconds.values())
    assert one_more > share - 0.01
    assert over.reasons == [
        f"the selection is {share:.0%} of the suite, past {share - 0.01:.0%}: it runs {over.share:.0%}"
    ]


def test_the_limit_is_forty_percent_of_test_time(tree: pathlib.Path) -> None:
    durations = DURATIONS | {"tests/test_plain.py": 12.0}  # tier 0 is 43 s of 113 s, 38%
    assert not fast_stage.make_plan(tree, set(), durations, set()).reasons
    assert fast_stage.make_plan(tree, set(), DURATIONS, set()).reasons  # 43 s of 102 s, 42%


def test_the_share_is_of_test_time_not_of_files(tree: pathlib.Path) -> None:
    plan = fast_stage.make_plan(tree, set(), DURATIONS, set(), limit=1.0)
    assert plan.selected_seconds == 40.0 + 1.0 + 1.0 + 1.0
    assert plan.share == pytest.approx(43.0 / sum(DURATIONS.values()))


def test_a_file_with_no_recorded_duration_costs_its_tests_at_the_recorded_mean() -> None:
    tests = {"tests/test_new.py": "def test_a(): pass\n\nasync def test_b(): pass\n"}
    tests |= {"tests/test_mail.py": "def test_a(): pass\n", "tests/test_plain.py": "def test_a(): pass\n"}
    known = {"tests/test_mail.py": 3.0, "tests/test_plain.py": 1.0}
    assert fast_stage.expected_seconds(tests, known) == {"tests/test_new.py": 4.0, **known}


# --- the base ---------------------------------------------------------------------------------


def _git(root: pathlib.Path, *arguments: str) -> str:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    author = ["-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    finished = subprocess.run(
        ["git", *author, *arguments], cwd=root, env=environment, capture_output=True, text=True, check=True
    )
    return finished.stdout.strip()


def _commit(root: pathlib.Path, files: dict[str, str]) -> str:
    _write(root, files)
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", "x")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, {".gitignore": "state/\n.pytest_cache/\n", "app/a.py": "", "app/b.py": "", "app/c.py": ""})
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def _advance_origin_main(repo: pathlib.Path) -> None:
    """main moves on without the branch: its tip is no longer where the two meet."""
    _git(repo, "checkout", "-q", "-b", "upstream", "origin/main")
    _commit(repo, {"app/c.py": "from main"})
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-q", "main")


def _green(root: pathlib.Path) -> None:
    for half in kept.HALVES:
        kept.begin(root, half)
    for half in kept.HALVES:
        kept.passed(root, half)
    assert (root / kept.GREEN).is_file()


def _noted(root: pathlib.Path, half: str = "python") -> dict:
    return json.loads((root / kept.STATE / f"{half}.json").read_text())


def test_with_no_green_run_the_base_is_the_merge_base(repo: pathlib.Path) -> None:
    fork = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"app/a.py": "1"})
    _advance_origin_main(repo)
    base = fast_stage.find_base(repo)
    assert base.sha == fork
    assert "merge base" in base.why
    assert fast_stage.changed_since(repo, base.sha) == ({"app/a.py"}, set())


def test_a_base_given_outright_is_where_it_meets_head(repo: pathlib.Path) -> None:
    fork = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"app/a.py": "1"})
    _green(repo)
    _advance_origin_main(repo)
    assert fast_stage.find_base(repo, "origin/main").sha == fork
    assert fast_stage.find_base(repo, "HEAD~1").sha == fork
    assert fast_stage.find_base(repo, "HEAD").sha == _git(repo, "rev-parse", "HEAD")
    with pytest.raises(SystemExit):
        fast_stage.find_base(repo, "no-such-ref")


def test_the_last_green_run_is_the_base_over_the_merge_base(repo: pathlib.Path) -> None:
    _commit(repo, {"app/a.py": "1"})
    _green(repo)
    green = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"app/b.py": "1"})
    base = fast_stage.find_base(repo)
    assert base.sha == green
    assert "last green" in base.why
    assert fast_stage.changed_since(repo, base.sha) == ({"app/b.py"}, set())


def test_a_base_that_moved_under_the_branch_counts_as_changed(repo: pathlib.Path) -> None:
    """The branch was green; main then moved under it and the branch was rebased. What main brought
    has not been tested with the branch, and the merge base alone would not show it."""
    _commit(repo, {"app/a.py": "branch"})
    _green(repo)
    _advance_origin_main(repo)
    _git(repo, "rebase", "-q", "upstream")
    committed, _ = fast_stage.changed_since(repo, fast_stage.find_base(repo).sha)
    assert "app/c.py" in committed
    merge_base = _git(repo, "merge-base", "origin/main", "HEAD")
    assert "app/c.py" not in fast_stage.changed_since(repo, merge_base)[0]


def test_a_commit_dropped_since_the_green_run_counts_as_changed(repo: pathlib.Path) -> None:
    """What the green run tested and the branch no longer has is a change too: the diff is from the green
    tree, not from where the two histories meet."""
    _commit(repo, {"app/b.py": "kept for a while"})
    _green(repo)
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    _commit(repo, {"app/a.py": "instead"})
    committed, _ = fast_stage.changed_since(repo, fast_stage.find_base(repo).sha)
    assert committed == {"app/a.py", "app/b.py"}


def test_uncommitted_and_untracked_changes_count(repo: pathlib.Path) -> None:
    _green(repo)
    _write(repo, {"app/a.py": "edited", "app/new.py": ""})
    assert fast_stage.changed_since(repo, fast_stage.find_base(repo).sha) == (set(), {"app/a.py", "app/new.py"})


def test_a_staged_change_counts(repo: pathlib.Path) -> None:
    _green(repo)
    _write(repo, {"app/a.py": "staged"})
    _git(repo, "add", "app/a.py")
    assert kept.read_json(repo / kept.GREEN) is not None
    assert fast_stage.changed_since(repo, fast_stage.find_base(repo).sha) == (set(), {"app/a.py"})


def test_a_rename_changes_both_names(repo: pathlib.Path) -> None:
    _green(repo)
    _git(repo, "mv", "app/a.py", "app/z.py")
    _git(repo, "commit", "-q", "-m", "rename")
    assert fast_stage.changed_since(repo, fast_stage.find_base(repo).sha)[0] == {"app/a.py", "app/z.py"}


def test_a_git_that_fails_is_no_answer_rather_than_no_change(repo: pathlib.Path) -> None:
    with pytest.raises(SystemExit):
        fast_stage.changed_since(repo, "0" * 40)


def test_a_green_run_on_a_commit_that_is_gone_falls_back_to_the_merge_base(repo: pathlib.Path) -> None:
    _write(repo, {kept.GREEN: json.dumps({"head": "0" * 40, "clean": True, "when": "then"})})
    assert "merge base" in fast_stage.find_base(repo).why


def test_begin_says_whether_the_tree_was_clean(repo: pathlib.Path) -> None:
    kept.begin(repo, "python")
    assert _noted(repo)["clean"] is True
    _write(repo, {"app/untracked.py": ""})
    kept.begin(repo, "python")
    assert _noted(repo)["clean"] is False
    (repo / "app/untracked.py").unlink()
    _write(repo, {"app/a.py": "edited"})
    kept.begin(repo, "python")
    assert _noted(repo)["clean"] is False


def test_a_tree_git_cannot_read_is_not_clean(tmp_path: pathlib.Path) -> None:
    kept.begin(tmp_path, "python")
    assert _noted(tmp_path)["clean"] is False


def test_there_are_two_halves_and_no_third(repo: pathlib.Path) -> None:
    assert kept.HALVES == ("python", "frontend")
    with pytest.raises(SystemExit):
        kept.begin(repo, "e2e")


# --- what a run leaves behind -----------------------------------------------------------------

JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite>
<testcase classname="tests.test_mail" name="test_a" time="1.5"/>
<testcase classname="tests.test_mail" name="test_b" time="0.5"/>
<testcase classname="tests.api.test_meetings.TestThem" name="test_c" time="2.0"/>
<testcase classname="tests.test_plain" name="test_d" time="0.25"/>
</testsuite></testsuites>"""


def test_the_junit_report_gives_seconds_by_file(tree: pathlib.Path) -> None:
    _write(tree, {"junit.xml": JUNIT})
    seconds = kept.read_junit(tree, tree / "junit.xml")
    assert seconds == {"tests/test_mail.py": 2.0, "tests/api/test_meetings.py": 2.0, "tests/test_plain.py": 0.25}


def test_green_is_both_halves_passed_on_one_commit_of_a_clean_tree(repo: pathlib.Path) -> None:
    for half in kept.HALVES:
        kept.begin(repo, half)
    kept.passed(repo, "python")
    assert not (repo / kept.GREEN).exists(), "pytest passed; vitest has not yet"
    kept.passed(repo, "frontend")
    assert json.loads((repo / kept.GREEN).read_text())["head"] == _git(repo, "rev-parse", "HEAD")


def test_a_half_that_was_noted_and_never_passed_is_no_green(repo: pathlib.Path) -> None:
    for half in kept.HALVES:
        kept.begin(repo, half)
    kept.passed(repo, "frontend")
    kept.passed(repo, "frontend")
    assert not (repo / kept.GREEN).exists()


def test_a_half_with_no_note_is_no_green(repo: pathlib.Path) -> None:
    """The Makefile removes a half's note before it runs; a `begin` that then fails leaves none."""
    kept.begin(repo, "frontend")
    kept.passed(repo, "python")
    kept.passed(repo, "frontend")
    assert not (repo / kept.GREEN).exists()


def test_halves_passed_on_two_commits_are_no_green(repo: pathlib.Path) -> None:
    kept.begin(repo, "python")
    kept.passed(repo, "python")
    _commit(repo, {"app/a.py": "moved on"})
    kept.begin(repo, "frontend")
    kept.passed(repo, "frontend")
    assert not (repo / kept.GREEN).exists()


def test_a_half_verify_skipped_counts_with_the_note_its_pass_left_on_the_same_commit(repo: pathlib.Path) -> None:
    """`verify` skips a stage whose files are as they were when it passed; the make target does not run,
    and the note its earlier pass left is what there is. On the commit the other half passes on, it is that
    commit's pass."""
    for half in kept.HALVES:
        kept.begin(repo, half)
    kept.passed(repo, "python")
    kept.passed(repo, "frontend")
    (repo / kept.GREEN).unlink()
    kept.begin(repo, "frontend")
    kept.passed(repo, "frontend")
    assert json.loads((repo / kept.GREEN).read_text())["head"] == _git(repo, "rev-parse", "HEAD")


def test_a_new_run_of_a_half_takes_back_its_earlier_pass(repo: pathlib.Path) -> None:
    kept.begin(repo, "python")
    kept.passed(repo, "python")
    kept.begin(repo, "python")
    kept.begin(repo, "frontend")
    kept.passed(repo, "frontend")
    assert not (repo / kept.GREEN).exists()


def test_a_full_run_on_a_dirty_tree_is_no_base_since_a_revert_would_read_as_no_change(repo: pathlib.Path) -> None:
    _commit(repo, {"tests/test_mail.py": ""})
    _write(repo, {"state/junit.xml": JUNIT, "app/a.py": "tested uncommitted"})
    for half in kept.HALVES:
        kept.begin(repo, half)
    kept.record(repo, repo / "state/junit.xml", 0, full=True)
    for half in kept.HALVES:
        kept.passed(repo, half)
    assert not (repo / kept.GREEN).exists()
    assert "tests/test_mail.py" in json.loads((repo / kept.DURATIONS).read_text())


def test_durations_come_from_runs_that_passed(tree: pathlib.Path) -> None:
    _write(tree, {"junit.xml": JUNIT, kept.DURATIONS: json.dumps({"tests/test_web_admin.py": 9.0})})
    kept.record(tree, tree / "junit.xml", 1, full=False)
    assert json.loads((tree / kept.DURATIONS).read_text()) == {"tests/test_web_admin.py": 9.0}
    kept.record(tree, tree / "junit.xml", 0, full=False)
    assert json.loads((tree / kept.DURATIONS).read_text())["tests/test_web_admin.py"] == 9.0
    kept.record(tree, tree / "junit.xml", 0, full=True)
    assert "tests/test_web_admin.py" not in json.loads((tree / kept.DURATIONS).read_text())


# --- vitest -----------------------------------------------------------------------------------


def test_vitest_runs_what_is_related_to_the_changed_sources(tree: pathlib.Path) -> None:
    _write(tree, {"assets/src/js/x.ts": "", "assets/src/js/X.svelte": "", "assets/src/js/y.js": ""})
    changed = {"assets/src/js/x.ts", "assets/src/js/X.svelte", "assets/src/js/y.js", "assets/src/css/app.css"}
    assert fast_stage.vitest_command(tree, changed) == [
        "yarn",
        "vitest",
        "related",
        "--run",
        "src/js/X.svelte",
        "src/js/x.ts",
        "src/js/y.js",
    ]


def test_a_deleted_or_renamed_source_runs_all_of_vitest(tree: pathlib.Path) -> None:
    _write(tree, {"assets/src/js/new-name.ts": ""})
    changed = {"assets/src/js/old-name.ts", "assets/src/js/new-name.ts"}
    assert fast_stage.vitest_command(tree, changed) == ["yarn", "test"]


@pytest.mark.parametrize("path", ["assets/package.json", "assets/vitest.config.ts", "assets/yarn.lock"])
def test_vitests_own_configuration_runs_all_of_vitest(tree: pathlib.Path, path: str) -> None:
    assert fast_stage.vitest_command(tree, {path}) == ["yarn", "test"]


def test_no_frontend_change_runs_no_vitest(tree: pathlib.Path) -> None:
    assert fast_stage.vitest_command(tree, {"app/mail.py", "assets/src/css/app.css"}) is None


# --- the stage itself -------------------------------------------------------------------------


@pytest.fixture
def bulk(repo: pathlib.Path) -> pathlib.Path:
    """A suite whose bulk the change does not reach, so that what it selects is a selection; the bulk
    says so if it runs."""
    _commit(repo, {"tests/test_bulk.py": "def test_a():\n    open('bulk-ran', 'a').close()\n"})
    durations = {"tests/test_bulk.py": 100.0, "tests/test_one.py": 1.0, "tests/test_two.py": 1.0}
    _write(repo, {kept.DURATIONS: json.dumps(durations)})
    return repo


def test_the_stage_stops_at_the_first_failure_runs_it_once_and_says_it_is_not_the_gate(
    bulk: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = bulk
    counted = "def test_a():\n    with open('ran', 'a') as f:\n        f.write('{}')\n    assert False\n"
    _commit(repo, {"tests/test_one.py": counted.format(1), "tests/test_two.py": counted.format(2)})
    status = fast_stage.run(repo, "HEAD~1", [])
    said = capsys.readouterr().out
    assert status == 1
    assert (repo / "ran").read_text() == "1"
    assert "tests/test_one.py  <- changed" in said
    assert "Fast stage FAILED" in said
    assert said.rstrip().endswith(fast_stage.NOT_THE_GATE)
    assert fast_stage.failed_before(repo) == {"tests/test_one.py"}


def test_the_stage_runs_the_selection_alone_and_records_its_durations_but_no_green(
    bulk: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = bulk
    _commit(repo, {"tests/test_one.py": "def test_a():\n    pass\n"})
    for half in kept.HALVES:
        kept.begin(repo, half)
    kept.passed(repo, "python")  # a fast run that marked the other half would make this green
    assert fast_stage.run(repo, "HEAD~1", []) == 0
    assert "Fast stage passed" in capsys.readouterr().out
    assert not (repo / "bulk-ran").exists()
    assert not (repo / kept.GREEN).exists()
    assert json.loads((repo / kept.DURATIONS).read_text())["tests/test_one.py"] != 1.0  # measured, not seeded


def test_the_stage_selects_what_is_uncommitted(bulk: pathlib.Path) -> None:
    repo = bulk
    _write(repo, {"tests/test_one.py": "def test_a():\n    pass\n"})
    assert fast_stage.run(repo, "HEAD", []) == 0


def test_the_stage_runs_what_failed_last_first(bulk: pathlib.Path) -> None:
    repo = bulk
    two = "def test_a():\n    open('ran', 'a').write('a')\n\ndef test_b():\n    open('ran', 'a').write('b')\n    assert False\n"
    _commit(repo, {"tests/test_one.py": two})
    assert fast_stage.run(repo, "HEAD~1", []) == 1
    assert fast_stage.run(repo, "HEAD~1", []) == 1
    assert (repo / "ran").read_text() == "abb"


def test_the_stage_passes_its_arguments_to_pytest(bulk: pathlib.Path) -> None:
    repo = bulk
    skipped = "def test_a():\n    pass\n\ndef test_skipme():\n    open('skipped-ran', 'a').close()\n"
    _commit(repo, {"tests/test_one.py": skipped})
    assert fast_stage.run(repo, "HEAD~1", ["-k", "not skipme"]) == 0
    assert not (repo / "skipped-ran").exists()


def test_a_change_that_needs_the_whole_suite_runs_its_selection_and_never_passes(
    bulk: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole suite wants the memory `make container-test` sizes: run here, six workers in the fixed
    cap were killed for it. So the stage runs what it selected, names that run, and answers with a
    status no test failure has - also when everything it ran passed."""
    repo = bulk
    _commit(repo, {"pyproject.toml": "", "tests/test_one.py": "def test_a():\n    open('ran', 'a').close()\n"})
    status = fast_stage.run(repo, "HEAD~1", [])
    said = capsys.readouterr().out
    assert status == fast_stage.NEEDS_THE_SUITE
    assert status not in range(6)
    assert (repo / "ran").exists()
    assert not (repo / "bulk-ran").exists()
    assert "pyproject.toml: the dependencies" in said
    assert "`make container-test`" in said
    assert "`FAST_BASE=HEAD`" in said
    assert "Fast stage passed" not in said
    assert said.rstrip().endswith(fast_stage.NOT_THE_GATE)


def test_a_change_that_needs_the_whole_suite_and_selects_nothing_does_not_pass(bulk: pathlib.Path) -> None:
    repo = bulk
    _commit(repo, {"pyproject.toml": ""})
    assert fast_stage.run(repo, "HEAD~1", []) == fast_stage.NEEDS_THE_SUITE
    assert not (repo / "bulk-ran").exists()


def test_an_empty_selection_runs_nothing_rather_than_everything(
    bulk: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = bulk
    _commit(repo, {"docs/x.md": "words"})
    assert fast_stage.run(repo, "HEAD~1", []) == fast_stage.NOTHING_SELECTED
    assert "selected no test file" in capsys.readouterr().out
    assert not (repo / "bulk-ran").exists()


def test_vitest_runs_after_pytest_passes_and_its_failure_is_the_stages(
    bulk: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = bulk
    seen: list[set[str]] = []

    def vitest(root: pathlib.Path, changed: set[str]) -> list[str]:
        seen.append(changed)
        return ["sh", "-c", "echo x >> ../vitest-ran; exit 3"]

    monkeypatch.setattr(fast_stage, "vitest_command", vitest)
    (repo / "assets").mkdir()
    _commit(repo, {"tests/test_one.py": "def test_a():\n    pass\n", "assets/src/committed.ts": ""})
    _write(repo, {"assets/src/x.ts": ""})
    assert fast_stage.run(repo, "HEAD~1", []) == 3
    assert {"assets/src/x.ts", "assets/src/committed.ts"} <= seen[0]
    _commit(repo, {"tests/test_one.py": "def test_a():\n    assert False\n"})
    assert fast_stage.run(repo, "HEAD~1", []) == 1
    assert (repo / "vitest-ran").read_text() == "x\n"


@pytest.mark.parametrize(("target", "half"), [("test-python", "python"), ("test-frontend", "frontend")])
def test_a_full_run_of_a_half_clears_its_last_note_before_it_begins(target: str, half: str) -> None:
    """`begin` may fail without stopping the run - `uv run` can fail before Python starts - and `passed`
    would then mark the last run's note, and take a commit whose run failed as green. Each half's recipe
    removes its note first, with a line whose failure does stop it, and marks it only after the run."""
    makefile_path = _CI.parent.parent / "Makefile"
    if not makefile_path.exists():
        pytest.skip("the kit has no Makefile: a service that copies this test reads its own")
    makefile = makefile_path.read_text(encoding="utf-8").splitlines()
    recipe = makefile[makefile.index(f"{target}:") + 1 :]
    recipe = recipe[: next(i for i, line in enumerate(recipe) if not line.startswith("\t"))]
    begin = next(i for i, line in enumerate(recipe) if f"$(FAST_STAGE) begin {half}" in line)
    clears = [i for i, line in enumerate(recipe[:begin]) if f"rm -f state/fast-stage/{half}.json" in line]
    marks = [i for i, line in enumerate(recipe) if f"$(FAST_STAGE) passed {half}" in line]

    assert clears, f"no line before `begin` removes state/fast-stage/{half}.json"
    assert not recipe[clears[0]].lstrip("\t").startswith("-")
    assert marks == [len(recipe) - 1], "`passed` is not the last line, after the run"
