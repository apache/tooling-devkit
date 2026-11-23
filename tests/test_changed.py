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

"""What `make check` and `make check-all` are told to check (`scripts/ci/changed.py`)."""

import importlib.util
import pathlib
import subprocess

import pytest

_CI = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ci"
spec = importlib.util.spec_from_file_location("changed", _CI / "changed.py")
assert spec and spec.loader
changed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changed)


def _git(where: pathlib.Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=where, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.org"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(tmp_path, "config", key, value)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("1\n")
    _git(tmp_path, "add", "app/a.py")
    _git(tmp_path, "commit", "-q", "-m", "first")
    monkeypatch.setattr(changed, "ROOT", tmp_path)
    return tmp_path


class TestEverything:
    def test_untracked_files_are_among_them(self, repo: pathlib.Path) -> None:
        (repo / "app" / "new.py").write_text("2\n")
        assert changed.everything() == ["app/a.py", "app/new.py"]


class TestSelection:
    def test_the_files_changed_since_the_ref_and_the_untracked_ones(self, repo: pathlib.Path) -> None:
        (repo / "app" / "a.py").write_text("2\n")
        (repo / "app" / "new.py").write_text("3\n")
        files, _ = changed.selection("main")
        assert files == ["app/a.py", "app/new.py"]

    def test_a_git_that_fails_is_not_nothing_changed(self, repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        real = changed._git

        def failing(*arguments: str) -> tuple[int, str]:
            return (128, "") if arguments[0] == "ls-files" else real(*arguments)

        monkeypatch.setattr(changed, "_git", failing)
        with pytest.raises(SystemExit) as stopped:
            changed.selection("main")
        assert "ls-files" in str(stopped.value)

    def test_a_diff_that_fails_is_not_nothing_changed(
        self, repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = changed._git

        def failing(*arguments: str) -> tuple[int, str]:
            return (128, "") if arguments[0] == "diff" else real(*arguments)

        monkeypatch.setattr(changed, "_git", failing)
        with pytest.raises(SystemExit) as stopped:
            changed.selection("main")
        assert "diff" in str(stopped.value)

    def test_the_whole_tree_listing_that_fails_is_not_an_empty_tree(
        self, repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(changed, "_git", lambda *arguments: (128, ""))
        with pytest.raises(SystemExit):
            changed.everything()


class TestAll:
    def test_check_all_hands_prek_every_file_untracked_ones_too(
        self, repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repo / "app" / "new.py").write_text("2\n")
        ran: list[list[str]] = []

        real = subprocess.run

        def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
            if command[0] != "prek":
                return real(command, **options)
            ran.append(command)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(changed.subprocess, "run", run)
        monkeypatch.setattr(changed.sys, "argv", ["changed.py", "--all"])
        assert changed.main() == 0
        assert ran == [["prek", "run", "--files", "app/a.py", "app/new.py"]]
