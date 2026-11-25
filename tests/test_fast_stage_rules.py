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

"""What a repository adds to the fast stage (`scripts/ci/fast_stage_rules.py`)."""

import importlib.util
import pathlib
import sys

import pytest

_CI = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ci"


def _module() -> object:
    """The module as another test file has loaded it, else loaded here."""
    if "fast_stage_rules" in sys.modules:
        return sys.modules["fast_stage_rules"]
    spec = importlib.util.spec_from_file_location("fast_stage_rules", _CI / "fast_stage_rules.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["fast_stage_rules"] = module
    spec.loader.exec_module(module)
    return module


rules = _module()
KIT = {"pyproject.toml": "the dependencies", "app/__init__.py": "startup"}


def _file(root: pathlib.Path, text: str) -> pathlib.Path:
    path = root / rules.LOCAL
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return root


class TestLoad:
    def test_no_file_is_the_kit_alone_and_no_broad_package(self, tmp_path: pathlib.Path) -> None:
        found = rules.load_rules(tmp_path, KIT)
        assert found.full_when == KIT
        assert found.broad_packages == frozenset()

    def test_a_file_adds_to_the_kit_after_its_own(self, tmp_path: pathlib.Path) -> None:
        root = _file(tmp_path, 'broad_packages = ["api", "md"]\n[full_when]\n"server.py" = "startup"\n')
        found = rules.load_rules(root, KIT)
        assert list(found.full_when.items()) == [*KIT.items(), ("server.py", "startup")]
        assert found.broad_packages == {"api", "md"}

    def test_the_kits_own_globs_are_not_changed(self, tmp_path: pathlib.Path) -> None:
        kit = dict(KIT)
        rules.load_rules(_file(tmp_path, '[full_when]\n"server.py" = "startup"\n'), kit)
        assert kit == KIT

    def test_an_empty_file_is_the_kit_alone(self, tmp_path: pathlib.Path) -> None:
        assert rules.load_rules(_file(tmp_path, ""), KIT) == rules.Rules(KIT)


class TestRefused:
    @pytest.mark.parametrize(
        ("text", "said"),
        [
            ("nonsense = 1\n", "'nonsense' is not a key"),
            ("broad_packages = 'api'\n", "broad_packages is a list of non-empty strings"),
            ("broad_packages = ['']\n", "broad_packages is a list of non-empty strings"),
            ("broad_packages = [1]\n", "broad_packages is a list of non-empty strings"),
            ("broad_packages = ['app/api']\n", "is a directory name under app/, with no `/`"),
            ("full_when = 'x'\n", "full_when is a table"),
            ("[full_when]\n'' = 'why'\n", "a glob in full_when is empty"),
            ("[full_when]\n'server.py' = ''\n", "says why"),
            ("[full_when]\n'server.py' = 3\n", "says why"),
            ("[full_when]\n'uv.lock' = 'x'\n", "full_when.'uv.lock' is the kit's already"),
            ("broad_packages = [\n", "cannot be read"),
        ],
    )
    def test_each_reason(self, tmp_path: pathlib.Path, text: str, said: str) -> None:
        kit = {**KIT, "uv.lock": "the dependencies"}
        with pytest.raises(rules.LocalError, match=said):
            rules.load_rules(_file(tmp_path, text), kit)

    def test_every_reason_at_once(self, tmp_path: pathlib.Path) -> None:
        root = _file(tmp_path, "nonsense = 1\nbroad_packages = [1]\n[full_when]\n'' = 'x'\n")
        with pytest.raises(rules.LocalError) as raised:
            rules.load_rules(root, KIT)
        assert len(str(raised.value).splitlines()) == 3
