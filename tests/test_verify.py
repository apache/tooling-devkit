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

"""What the gate runs again, and what it takes on trust from an earlier pass (`scripts/ci/verify.py`).

A stage skipped although what it reads changed passes a change it never looked at, which is the failure
that matters; a stage run although nothing changed only costs time. So each way of changing what a
stage reads is pinned to running it again, in a repository of its own with a Makefile whose targets
say each time they run.
"""

import importlib.util
import pathlib
import subprocess
import sys
import textwrap

import pytest

_CI = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ci"
spec = importlib.util.spec_from_file_location("verify", _CI / "verify.py")
assert spec and spec.loader
verify = importlib.util.module_from_spec(spec)
sys.modules["verify"] = verify
spec.loader.exec_module(verify)

MAKEFILE = """\
# what each target does is say that it ran
one:
\techo one >> "$$RUNS"

PYTEST_WORKERS ?= 6
workers:
\techo workers-$(PYTEST_WORKERS) >> "$$RUNS"

fails:
\techo fails >> "$$RUNS"; exit 1

rewrites:
\techo rewrites >> "$$RUNS"; echo again >> tracked.txt

# each waits for the other to start: run one after the other, the first gives up
first:
\ttouch "$$RUNS.first"; for i in $$(seq 100); do [ -f "$$RUNS.second" ] && exit 0; sleep 0.1; done; exit 1

second:
\ttouch "$$RUNS.second"; for i in $$(seq 100); do [ -f "$$RUNS.first" ] && exit 0; sleep 0.1; done; exit 1
"""


def _git(root: pathlib.Path, *arguments: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *arguments], cwd=root, check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> pathlib.Path:
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "MAKEFLAGS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("RUNS", str(tmp_path / "runs"))
    _git(root, "init", "--quiet")
    (root / ".gitignore").write_text("state/\nignored.txt\n")
    (root / "Makefile").write_text(MAKEFILE)
    (root / "tracked.txt").write_text("as committed\n")
    (root / "sub").mkdir()
    (root / "sub" / "inside.txt").write_text("as committed\n")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "start")
    monkeypatch.setattr(verify, "ROOT", root)
    monkeypatch.setattr(verify, "STATE", root / "state" / "verify")
    verify.STATE.mkdir(parents=True)
    return root


def _runs(repo: pathlib.Path) -> list[str]:
    runs = repo.parent / "runs"
    return runs.read_text().split() if runs.exists() else []


NO_CONFIG = verify.Config(stages=(), extras={}, environment=())


def _verdict(stage: verify.Stage, config: verify.Config = NO_CONFIG, *, fresh: bool = False) -> str:
    return verify.run(stage, config, fresh=fresh).verdict


def _config(repo: pathlib.Path, text: str) -> pathlib.Path:
    path = repo / "verify.toml"
    path.write_text(textwrap.dedent(text))
    return path


ONE = verify.Stage("one")


def test_a_stage_that_passed_is_not_run_again_while_nothing_changes(repo) -> None:
    assert [_verdict(ONE), _verdict(ONE)] == ["passed", "unchanged"]
    assert _runs(repo) == ["one"]


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda root: (root / "tracked.txt").write_text("edited\n"), id="an edit not committed"),
        pytest.param(lambda root: (root / "new.txt").write_text("new\n"), id="a file not yet tracked"),
        pytest.param(lambda root: (root / "tracked.txt").unlink(), id="a file deleted"),
        pytest.param(
            lambda root: (root / "Makefile").write_text(MAKEFILE.replace('echo one >> "$$RUNS"', 'echo 1 >> "$$RUNS"')),
            id="what its target runs",
        ),
    ],
)
def test_a_change_to_what_a_stage_reads_runs_it_again(repo, change) -> None:
    _verdict(ONE)
    change(repo)

    assert _verdict(ONE) == "passed"
    assert len(_runs(repo)) == 2


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda root: (root / "ignored.txt").write_text("x\n"), id="a file git ignores"),
        pytest.param(
            lambda root: (root / "Makefile").write_text(MAKEFILE.replace("# what each", "# what every")),
            id="a comment in the Makefile",
        ),
    ],
)
def test_what_a_stage_does_not_read_does_not_run_it_again(repo, change) -> None:
    _verdict(ONE)
    change(repo)

    assert _verdict(ONE) == "unchanged"


def test_a_setting_that_narrows_pytest_runs_it_again(repo, monkeypatch) -> None:
    """`-k` or `--lf` in PYTEST_ADDOPTS runs some of the suite: its pass is not a pass of all of it."""
    _verdict(ONE)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k rename")

    assert _verdict(ONE) == "passed"


def test_how_many_workers_pytest_is_given_does_not_run_it_again(repo, monkeypatch) -> None:
    """scripts/container-size.sh gives a run as many workers as the machine has room for, and that
    changes how long the suite takes, not what it checks."""
    workers = verify.Stage("workers")
    monkeypatch.setenv("PYTEST_WORKERS", "6")
    _verdict(workers)
    monkeypatch.setenv("PYTEST_WORKERS", "3")

    assert _verdict(workers) == "unchanged"
    assert _runs(repo) == ["workers-6"]


def test_a_file_hidden_by_info_exclude_is_still_read(repo) -> None:
    """Only the .gitignore files say what no stage reads: a test file hidden through .git/info/exclude
    is still one pytest collects."""
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "exclude").write_text("hidden_test.py\n")
    (repo / "hidden_test.py").write_text("def test_x(): pass\n")
    _verdict(ONE)
    (repo / "hidden_test.py").write_text("def test_x(): assert False\n")

    assert _verdict(ONE) == "passed"


def test_a_comment_in_the_makefile_runs_a_stage_that_reads_the_makefile(repo) -> None:
    """The hooks lint it, and the behaviour selection records everything for any change to it."""
    reading = verify.Stage("one", reads_makefile=True)
    _verdict(reading)
    (repo / "Makefile").write_text(MAKEFILE.replace("# what each", "# what every"))

    assert _verdict(reading) == "passed"


def test_a_stage_that_reads_some_of_the_tree_runs_again_only_for_those_files(repo) -> None:
    inside = verify.Stage("one", paths=("sub/",))
    _verdict(inside)

    (repo / "tracked.txt").write_text("edited\n")
    assert _verdict(inside) == "unchanged"

    (repo / "sub" / "inside.txt").write_text("edited\n")
    assert _verdict(inside) == "passed"


def test_a_change_to_what_else_a_stage_depends_on_runs_it_again(repo) -> None:
    """The base it compares against, say: a file that is not part of the tree."""
    config = verify.Config(
        stages=(), extras={"base": verify.Extra("file", path="state/base.json")}, environment=()
    )
    based = verify.Stage("one", extras=("base",))
    (repo / "state" / "base.json").write_text("recorded with abc\n")
    _verdict(based, config)

    (repo / "state" / "base.json").write_text("recorded with def\n")
    assert _verdict(based, config) == "passed"


def test_a_setting_a_repository_names_runs_a_stage_again(repo, monkeypatch) -> None:
    config = verify.Config(stages=(), extras={}, environment=("A_SETTING",))
    _verdict(ONE, config)
    monkeypatch.setenv("A_SETTING", "narrower")

    assert _verdict(ONE, config) == "passed"


def test_the_settings_of_every_repository_are_read_whatever_its_file_says(repo, monkeypatch) -> None:
    for name in ("DEVKIT_PYTHON", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(name, raising=False)
        _verdict(ONE)
        monkeypatch.setenv(name, "different")

        assert _verdict(ONE) == "passed", name


def test_a_failure_is_not_remembered(repo) -> None:
    failing = verify.Stage("fails")

    assert [_verdict(failing), _verdict(failing)] == ["failed", "failed"]
    assert _runs(repo) == ["fails", "fails"]


def test_a_stage_that_changed_the_tree_while_it_ran_is_not_remembered_for_the_tree_before(repo) -> None:
    """A file edited while pytest read it - a fix made during the run, say: what passed is neither the
    tree before nor the tree after. Recording the tree before would pass it again once the edit is
    undone, though it was never the tree that passed."""
    rewrites = verify.Stage("rewrites")
    _verdict(rewrites)

    (repo / "tracked.txt").write_text("as committed\n")
    assert _verdict(rewrites) == "passed"


def test_a_stage_that_changed_the_tree_while_it_ran_is_not_remembered_for_the_tree_after(repo) -> None:
    """Nor the tree after: the stage never ran against it."""
    rewrites = verify.Stage("rewrites")
    _verdict(rewrites)

    assert _verdict(rewrites) == "passed"


def test_fresh_runs_a_stage_that_passed(repo) -> None:
    _verdict(ONE)

    assert _verdict(ONE, fresh=True) == "passed"
    assert _runs(repo) == ["one", "one"]


def test_the_stages_run_at_the_same_time(repo) -> None:
    config = _config(repo, """
        [[stages]]
        name = "first"
        [[stages]]
        name = "second"
    """)

    assert verify.main(["--config", str(config)]) == 0


def test_the_gate_fails_when_one_stage_does_and_runs_the_others_all_the_same(repo, capsys) -> None:
    config = _config(repo, """
        [[stages]]
        name = "fails"
        [[stages]]
        name = "one"
    """)

    assert verify.main(["--config", str(config)]) == 1
    assert sorted(_runs(repo)) == ["fails", "one"]
    assert "verify: FAILED - fails" in capsys.readouterr().out


def test_one_stage_named_runs_alone(repo) -> None:
    config = _config(repo, """
        [[stages]]
        name = "one"
        [[stages]]
        name = "fails"
    """)

    assert verify.main(["--config", str(config), "one"]) == 0
    assert _runs(repo) == ["one"]


def test_a_stage_the_file_does_not_name_is_refused_with_the_ones_it_does(repo, capsys) -> None:
    config = _config(repo, """
        [[stages]]
        name = "one"
    """)

    with pytest.raises(SystemExit):
        verify.main(["--config", str(config), "two"])
    assert "no stage two: the stages are one" in capsys.readouterr().err


def test_a_repository_without_a_file_is_told_where_it_goes(repo, capsys) -> None:
    assert verify.main(["--config", str(repo / "scripts" / "local" / "verify.toml")]) == 2
    assert "verify.toml cannot be read" in capsys.readouterr().err


# --- what an extra holds ----------------------------------------------------------------------------


def test_a_file_that_is_not_there_and_then_is_changes_what_a_stage_depends_on(repo) -> None:
    extra = verify.Extra("file", path="state/built.json")
    absent = verify.extra_text(extra)
    (repo / "state" / "built.json").write_text('{"main.js": "main-1a2b.js"}\n')

    assert verify.extra_text(extra) not in (absent, "")
    assert absent.startswith("no ")


def test_a_file_is_read_where_the_makefile_says_it_is(repo, monkeypatch) -> None:
    (repo / "state" / "elsewhere.json").write_text('{"commit": "abc"}\n')
    monkeypatch.setenv("A_BASE", "state/elsewhere.json")

    assert verify.extra_text(verify.Extra("file", path="state/base.json", env="A_BASE")) == '{"commit": "abc"}\n'
    monkeypatch.delenv("A_BASE")
    assert verify.extra_text(verify.Extra("file", path="state/base.json", env="A_BASE")).startswith("no ")


def test_a_trailer_added_by_an_amend_changes_what_a_stage_depends_on(repo, monkeypatch) -> None:
    _git(repo, "branch", "base")
    (repo / "tracked.txt").write_text("a change\n")
    _git(repo, "commit", "--quiet", "-am", "a change")
    monkeypatch.setenv("VERIFY_REF", "base")
    trailers = verify.Extra("trailers")
    before = verify.extra_text(trailers)

    _git(repo, "commit", "--quiet", "--amend", "-m", "a change\n\nBehaviour-Allow: http/x.txt")

    assert verify.extra_text(trailers) != before


def test_the_trailers_of_a_branch_with_no_base_say_so(repo, monkeypatch) -> None:
    monkeypatch.setenv("VERIFY_REF", "no-such-ref")

    assert verify.extra_text(verify.Extra("trailers")) == "no merge base"


def test_what_a_command_prints_and_how_it_ended_is_what_a_stage_depends_on(repo) -> None:
    printing = verify.Extra("command", run="cat tracked.txt")
    before = verify.extra_text(printing)
    (repo / "tracked.txt").write_text("edited\n")

    assert verify.extra_text(printing) != before
    assert verify.extra_text(verify.Extra("command", run="exit 3")).startswith("exit 3")
    assert verify.extra_text(verify.Extra("command", run="true")).startswith("exit 0")


# --- what the file may say -------------------------------------------------------------------------

VALID = """
    environment = ["MINUTES_CORPUS"]

    [extras.quality-base]
    kind = "file"
    path = "state/quality-base.json"
    env = "QUALITY_BASE"

    [extras.trailers]
    kind = "trailers"

    [extras.corpus]
    kind = "command"
    run = "ls state"

    [[stages]]
    name = "test-python"
    extras = ["corpus"]
    longest = true

    [[stages]]
    name = "lint"
    paths = ["assets/", "tests/data/"]
    reads_makefile = true
    extras = ["quality-base", "trailers"]
"""


def test_a_file_that_says_what_the_stages_are_is_read(repo) -> None:
    config = verify.load_config(_config(repo, VALID))

    assert config.environment == ("MINUTES_CORPUS",)
    assert config.extras["quality-base"] == verify.Extra("file", path="state/quality-base.json", env="QUALITY_BASE")
    assert config.extras["trailers"] == verify.Extra("trailers")
    assert config.extras["corpus"] == verify.Extra("command", run="ls state")
    first, second = config.stages
    assert (first.name, first.paths, first.extras, first.longest) == ("test-python", None, ("corpus",), True)
    assert (second.paths, second.reads_makefile, second.extras) == (
        ("assets/", "tests/data/"),
        True,
        ("quality-base", "trailers"),
    )


@pytest.mark.parametrize(
    ("text", "says"),
    [
        pytest.param("", "there is no [[stages]]", id="nothing"),
        pytest.param("not toml at all [", "is not TOML", id="not TOML"),
        pytest.param('[[stages]]\nname = "a"\nfoo = 1\n', "stage 1 (a) has no foo", id="a key it does not know"),
        pytest.param('stage = 1\n[[stages]]\nname = "a"\n', "stage is not a setting", id="a setting it does not know"),
        pytest.param("[[stages]]\npaths = []\n", "stage 1 has a name that is a make target", id="no name"),
        pytest.param('[[stages]]\nname = "../up"\n', "has a name that is a make target", id="a name that is a path"),
        pytest.param('[[stages]]\nname = "a"\n[[stages]]\nname = "a"\n', "stage 2 (a) is named twice", id="twice"),
        pytest.param('[[stages]]\nname = "a"\nextras = ["x"]\n', "no extra named x", id="an extra that is not defined"),
        pytest.param('[[stages]]\nname = "a"\npaths = "assets/"\n', "paths is a list of strings", id="paths as a string"),
        pytest.param('[[stages]]\nname = "a"\nlongest = "yes"\n', "longest is true or false", id="a flag that is not one"),
        pytest.param('environment = ["A B"]\n[[stages]]\nname = "a"\n', "A B is not a variable name", id="a bad variable"),
        pytest.param('[extras.x]\nkind = "other"\n[[stages]]\nname = "a"\n', "extras.x has a kind of", id="a kind it lacks"),
        pytest.param('[extras.x]\nkind = "file"\n[[stages]]\nname = "a"\n', "extras.x gives path as a string", id="a file with no path"),
        pytest.param('[extras.x]\nkind = "command"\n[[stages]]\nname = "a"\n', "extras.x gives run as a string", id="a command with none"),
        pytest.param('[extras.x]\nkind = "trailers"\npath = "p"\n[[stages]]\nname = "a"\n', "extras.x: no path for a trailers", id="a key the kind has no use for"),
    ],
)
def test_what_cannot_be_run_is_refused_and_says_why(repo, text, says) -> None:
    with pytest.raises(verify.ConfigError) as error:
        verify.load_config(_config(repo, text))

    assert says in str(error.value)


def test_every_reason_is_given_at_once(repo) -> None:
    text = '[[stages]]\nname = "a"\nfoo = 1\nextras = ["x"]\nlongest = "yes"\n'
    with pytest.raises(verify.ConfigError) as error:
        verify.load_config(_config(repo, text))

    assert [line.strip() for line in str(error.value).splitlines()[1:]] == [
        "stage 1 (a) has no foo",
        "stage 1 (a): no extra named x",
        "stage 1 (a): longest is true or false",
    ]
