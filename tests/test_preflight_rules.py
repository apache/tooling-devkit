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

"""What a repository may say in `scripts/local/preflight.toml`, and what the shell script is given from it
(`scripts/ci/preflight_rules.py`).

The script reads the helper's lines and not the file, so each fact has to arrive as one line, in order,
with nothing the shell would read as two.
"""

import importlib.util
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


rules = _load("preflight_rules")


def _file(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    path = tmp_path / "preflight.toml"
    path.write_text(text)
    return path


def test_the_facts_of_the_rules_come_in_the_order_of_the_file(tmp_path) -> None:
    path = _file(
        tmp_path,
        """
        [[rules]]
        title = "the interface"
        touches = ["^assets/", "^app/templates/"]
        say = ["Read the design book.", "Add tests."]

        [[rules]]
        title = "a component that fetches"
        touches = "^components/.*\\\\.svelte$"
        reads = "(fetch\\\\(|await )"
        reads_in = ["^components/", "^pages/"]
        say = ["Answer these."]

        [[rules]]
        title = "new files"
        adds = "\\\\.py$"
        say = ["A header."]
        """,
    )

    assert rules.load(path) == [
        ("rule", "the interface"),
        ("touches", "^assets/"),
        ("touches", "^app/templates/"),
        ("say", "Read the design book."),
        ("say", "Add tests."),
        ("rule", "a component that fetches"),
        ("touches", "^components/.*\\.svelte$"),
        ("reads", "(fetch\\(|await )"),
        ("reads_in", "^components/"),
        ("reads_in", "^pages/"),
        ("say", "Answer these."),
        ("rule", "new files"),
        ("adds", "\\.py$"),
        ("say", "A header."),
    ]


def test_a_file_with_no_rules_has_none(tmp_path) -> None:
    assert rules.load(_file(tmp_path, "")) == []


@pytest.mark.parametrize(
    ("text", "says"),
    [
        pytest.param("this is [ not toml", "is not TOML", id="not TOML"),
        pytest.param("rule = 1\n", "rule is not a setting", id="a setting it does not know"),
        pytest.param('rules = "x"\n', "rules is a list of [[rules]] tables", id="rules that are not tables"),
        pytest.param('[[rules]]\ntouches = "a"\nsay = ["x"]\n', "title is a non-empty string", id="no title"),
        pytest.param('[[rules]]\ntitle = "t"\nsay = ["x"]\n', "has `touches` or `adds`, and not both", id="neither"),
        pytest.param('[[rules]]\ntitle = "t"\ntouches = "a"\nadds = "b"\nsay = ["x"]\n', "and not both", id="both"),
        pytest.param('[[rules]]\ntitle = "t"\ntouches = "a"\n', "say is a list of lines", id="no lines"),
        pytest.param('[[rules]]\ntitle = "t"\ntouches = "a"\nsay = []\n', "say is a list of lines", id="empty lines"),
        pytest.param('[[rules]]\ntitle = "t"\ntouches = "a"\nsay = ["x"]\nfoo = 1\n', "rule 1 (t) has no foo", id="a key it lacks"),
        pytest.param('[[rules]]\ntitle = "t"\ntouches = []\nsay = ["x"]\n', "touches is a pattern, or a list", id="no patterns"),
        pytest.param('[[rules]]\ntitle = "t"\nadds = "a"\nreads = "b"\nsay = ["x"]\n', "reads goes with `touches`", id="reads on adds"),
        pytest.param('[[rules]]\ntitle = "t"\ntouches = "a"\nreads_in = "b"\nsay = ["x"]\n', "reads_in goes with `reads`", id="reads_in alone"),
        pytest.param('[[rules]]\ntitle = "t"\ntouches = "a"\nsay = [1]\n', "say is a non-empty string", id="a line that is not text"),
    ],
)
def test_what_cannot_be_used_is_refused_and_says_why(tmp_path, text, says) -> None:
    with pytest.raises(rules.RulesError) as error:
        rules.load(_file(tmp_path, text))

    assert says in str(error.value)


@pytest.mark.parametrize("bad", ["a\\tb", "a\\nb", "a\\rb"])
@pytest.mark.parametrize("where", ["title", "touches", "say"])
def test_a_tab_or_a_line_break_is_refused_where_the_shell_would_read_it_as_two(tmp_path, where, bad) -> None:
    """The shell reads `kind<TAB>value`, one fact to a line."""
    fields = {"title": '"t"', "touches": '"a"', "say": '["x"]'}
    fields[where] = f'["{bad}"]' if where != "title" else f'"{bad}"'
    body = "\n".join(f"{key} = {value}" for key, value in fields.items())

    with pytest.raises(rules.RulesError) as error:
        rules.load(_file(tmp_path, f"[[rules]]\n{body}\n"))

    assert "tab or a line break" in str(error.value)


def test_every_reason_is_given_at_once(tmp_path) -> None:
    text = '[[rules]]\ntitle = "t"\nfoo = 1\nadds = "a"\ntouches = "b"\n'
    with pytest.raises(rules.RulesError) as error:
        rules.load(_file(tmp_path, text))

    assert [line.strip() for line in str(error.value).splitlines()[1:]] == [
        "rule 1 (t) has no foo",
        "rule 1 (t) has `touches` or `adds`, and not both",
        "rule 1 (t): say is a list of lines",
    ]


def test_a_file_that_is_not_there_is_said_not_a_traceback(tmp_path) -> None:
    with pytest.raises(rules.RulesError) as error:
        rules.load(tmp_path / "nowhere.toml")

    assert "cannot be read" in str(error.value)


def test_the_script_prints_a_fact_to_a_line(tmp_path, capsys) -> None:
    path = _file(tmp_path, '[[rules]]\ntitle = "t"\ntouches = "^a/"\nsay = ["x", "y"]\n')

    assert rules.main([str(path)]) == 0
    assert capsys.readouterr().out == "rule\tt\ntouches\t^a/\nsay\tx\nsay\ty\n"


def test_a_file_that_cannot_be_used_is_status_one_and_says_so_on_stderr(tmp_path, capsys) -> None:
    assert rules.main([str(_file(tmp_path, "oops ["))]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "is not TOML" in captured.err


def test_the_script_is_given_one_file(capsys) -> None:
    assert rules.main([]) == 2
    assert "usage" in capsys.readouterr().err
