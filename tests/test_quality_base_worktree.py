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

"""The quality base of a commit that is older than the tree (`scripts/ci/quality.py`, `_measure_worktree`)."""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import types

_CI = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ci"
sys.path.insert(0, str(_CI))


def _load(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, _CI / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for _name in ("trailers", "quality_meters", "quality_allowances", "quality_moves"):
    _load(_name)
quality = _load("quality")


def _git(where: pathlib.Path, *arguments: str) -> str:
    done = subprocess.run(["git", *arguments], cwd=where, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def test_a_commit_from_before_assets_existed_can_be_measured(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.org"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    (repo / "app.py").write_text("1\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-q", "-m", "a young tree: no assets/")
    seen: list[bool] = []

    def collect(names: list[str], **_: object) -> tuple[dict[str, dict[str, float]], list[str]]:
        seen.append((quality.quality_meters.TREE / "assets" / "node_modules").is_symlink())
        return {}, []

    monkeypatch.setattr(quality.quality_meters, "ROOT", repo)
    monkeypatch.setattr(quality.quality_meters, "TREE", repo)
    monkeypatch.setattr(quality, "collect", collect)
    assert quality._measure_worktree(_git(repo, "rev-parse", "HEAD"), ["python-cyclomatic"]) == {}
    assert seen == [True]
