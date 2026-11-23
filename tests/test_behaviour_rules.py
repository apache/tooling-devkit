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

"""What a repository adds to the behaviour comparison (`scripts/ci/behaviour_rules.py`)."""

import importlib.util
import pathlib
import sys

import pytest

_CI = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ci"


def _module(name: str) -> object:
    """The module as another test file has loaded it, else loaded here: `behaviour_rules` imports the others by
    name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _CI / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _module("behaviour_gate")
selection = _module("behaviour_selection")
rules = _module("behaviour_rules")


def _file(root: pathlib.Path, text: str) -> pathlib.Path:
    path = root / rules.LOCAL
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return root


class TestLoad:
    def test_no_file_is_the_kit_alone(self, tmp_path: pathlib.Path) -> None:
        found = rules.load_rules(tmp_path)
        assert found.everything_when == selection.EVERYTHING_WHEN
        assert found.harness_files == gate.HARNESS_FILES
        assert found.whole == selection.WHOLE

    def test_a_file_adds_to_the_kit_after_its_own(self, tmp_path: pathlib.Path) -> None:
        root = _file(
            tmp_path,
            'everything_when = ["schema/**"]\nharness_files = ["tests/data/wc/*"]\n[whole]\n"task " = "tasks"\n',
        )
        found = rules.load_rules(root)
        assert found.everything_when == (*selection.EVERYTHING_WHEN, "schema/**")
        assert found.harness_files == (*gate.HARNESS_FILES, "tests/data/wc/*")
        assert found.whole == {**selection.WHOLE, "task ": "tasks"}

    def test_the_kits_own_lists_are_not_changed(self, tmp_path: pathlib.Path) -> None:
        kit = (selection.EVERYTHING_WHEN, gate.HARNESS_FILES, dict(selection.WHOLE))
        rules.load_rules(_file(tmp_path, 'everything_when = ["schema/**"]\n[whole]\n"task " = "tasks"\n'))
        assert (selection.EVERYTHING_WHEN, gate.HARNESS_FILES, selection.WHOLE) == kit

    def test_an_empty_file_is_the_kit_alone(self, tmp_path: pathlib.Path) -> None:
        assert rules.load_rules(_file(tmp_path, "")) == rules.Rules()


class TestRefused:
    @pytest.mark.parametrize(
        ("text", "said"),
        [
            ("nonsense = 1\n", "'nonsense' is not a key"),
            ("everything_when = 'schema/**'\n", "everything_when is a list of non-empty strings"),
            ("harness_files = ['']\n", "harness_files is a list of non-empty strings"),
            ("everything_when = [1]\n", "everything_when is a list of non-empty strings"),
            ("everything_when = ['app/__init__.py']\n", "everything_when repeats what the kit has: app/__init__.py"),
            ("harness_files = ['tests/conftest.py']\n", "harness_files repeats what the kit has: tests/conftest.py"),
            ("whole = 'x'\n", "whole is a table"),
            ("[whole]\n'' = 'tasks'\n", "a prefix in whole is empty"),
            ("[whole]\n'task ' = 'a/b'\n", "names a directory"),
            ("[whole]\n'task ' = 3\n", "names a directory"),
            ("[whole]\n'scenario ' = 'other'\n", "is the kit's already"),
            ("everything_when = [\n", "cannot be read"),
        ],
    )
    def test_each_reason(self, tmp_path: pathlib.Path, text: str, said: str) -> None:
        with pytest.raises(rules.LocalError, match=said):
            rules.load_rules(_file(tmp_path, text))

    def test_every_reason_at_once(self, tmp_path: pathlib.Path) -> None:
        root = _file(tmp_path, "nonsense = 1\nharness_files = [1]\n[whole]\n'' = 'x'\n")
        with pytest.raises(rules.LocalError) as raised:
            rules.load_rules(root)
        assert len(str(raised.value).splitlines()) == 3
