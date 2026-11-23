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
"""A tree that has none of what the quality meters read: a young repository.

A meter that reads a path or a config file that is not there makes its tool fail, and the ratchet with
it, before there is anything to measure. Each reads nothing instead, and runs no tool at all.
"""

from __future__ import annotations

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


meters = _load("quality_meters")


@pytest.fixture
def empty_tree(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    def no_tool(*_arguments: object, **_keywords: object) -> str:
        raise AssertionError("a meter ran a tool over a tree with nothing for it to read")

    monkeypatch.setattr(meters, "TREE", tmp_path)
    monkeypatch.setattr(meters, "_run", no_tool)
    return tmp_path


def test_a_source_path_that_is_not_there_is_left_out(empty_tree: pathlib.Path) -> None:
    (empty_tree / "app").mkdir()

    assert meters._sources("app", "scripts", "server.py") == [str(empty_tree / "app")]


@pytest.mark.parametrize(
    "meter",
    [
        "python_cyclomatic",
        "python_cognitive",
        "python_dead_code",
        "frontend_complexity",
        "frontend_dead_code",
        "duplication",
    ],
)
def test_a_meter_reads_nothing_where_there_is_nothing_for_it(empty_tree: pathlib.Path, meter: str) -> None:
    assert getattr(meters, meter)() == {}


def test_the_source_files_of_a_tree_without_a_server_are_none(empty_tree: pathlib.Path) -> None:
    assert meters._source_files() == []
