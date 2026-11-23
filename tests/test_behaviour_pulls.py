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

"""What a full comparison reads from the pull requests merged as main's commits (`behaviour_pulls.py`).

GitHub is stood in for twice: its API by a dictionary, and its git by a scratch repository that holds
each pull request's head under `refs/pull/N/head`, as GitHub keeps it after the branch is deleted, and
that this checkout has to fetch it from.
"""

import base64
import dataclasses
import email.message
import io
import json
import subprocess
import sys
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from tests.test_behaviour_check import commit, gate, git, pulls

if TYPE_CHECKING:
    import pathlib

SQUASH = """\
feat: two changes (#7)

* feat: one

Behaviour-Allow: http/a.txt

* feat: two

Behaviour-Allow: tasks/b.txt
Behaviour-Harness: records more

---------

Co-authored-by: t <t@example.org>"""
"""The message GitHub writes for a squash merge by default: each commit's message, joined."""

BY_GITHUB = ("-c", "user.name=GitHub", "-c", "user.email=noreply@github.com")
"""Who commits a merge GitHub makes - and an edit made on GitHub's web page, straight to main."""


def init(where: pathlib.Path) -> pathlib.Path:
    where.mkdir()
    git(where, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.org"), ("user.name", "t"), ("commit.gpgsign", "false")):
        git(where, "config", key, value)
    return where


@dataclasses.dataclass
class Fake:
    """GitHub's API: the pull requests it lists for a commit, and each pull request by its number."""

    listed: dict[str, list[dict[str, Any]]] = dataclasses.field(default_factory=dict)
    numbered: dict[int, dict[str, Any]] = dataclasses.field(default_factory=dict)

    def pulls_of(self, sha: str) -> list[dict[str, Any]]:
        return self.listed.get(sha, [])

    def pull(self, number: int) -> dict[str, Any] | None:
        return self.numbered.get(number)


class Refusing:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def pulls_of(self, sha: str) -> list[dict[str, Any]]:
        raise self.error

    def pull(self, number: int) -> dict[str, Any] | None:
        raise self.error


class Merged:
    """GitHub's side: main with a push and a squash merge, and pull request 7's head kept where it keeps it.

    The pull request merged main into itself, and a side branch whose commit carries a trailer: neither is
    its own, and its own comparison read neither."""

    def __init__(self, tmp_path: pathlib.Path) -> None:
        self.origin = init(tmp_path / "origin")
        self.base = commit(self.origin, "base", {"a": "1"})
        git(self.origin, "checkout", "-q", "-b", "side")
        commit(self.origin, "side\n\nBehaviour-Allow: http/side.txt", {"s": "1"})
        git(self.origin, "checkout", "-q", "-b", "pull", self.base)
        commit(self.origin, "feat: one\n\nBehaviour-Allow: http/a.txt", {"b": "1"})
        git(self.origin, "checkout", "-q", "main")
        self.push = commit(self.origin, "a push to main\n\nBehaviour-Allow: http/pushed.txt", {"p": "1"})
        git(self.origin, "checkout", "-q", "pull")
        git(self.origin, "merge", "-q", "--no-ff", "main", "-m", "merge main\n\nBehaviour-Allow: http/merge.txt")
        git(self.origin, "merge", "-q", "--no-ff", "side", "-m", "merge side")
        self.tip = commit(self.origin, "feat: two\n\nBehaviour-Allow: tasks/b.txt\nBehaviour-Harness: records more", {})
        git(self.origin, "update-ref", "refs/pull/7/head", self.tip)
        git(self.origin, "checkout", "-q", "--detach", self.base)
        self.other = commit(self.origin, "feat: another\n\nBehaviour-Allow: http/other.txt", {})
        for number in (9, 10, 11, 30):
            git(self.origin, "update-ref", f"refs/pull/{number}/head", self.other)
        git(self.origin, "checkout", "-q", "main")
        git(self.origin, "branch", "-q", "-D", "pull", "side")
        self.squash = commit(self.origin, SQUASH, {"b": "1"})
        self.local = tmp_path / "local"
        git(tmp_path, "clone", "-q", str(self.origin), str(self.local))
        self.fetched: list[list[int]] = []

    def pull(self, number: int = 7, **fields: Any) -> dict[str, Any]:
        return {
            "number": number,
            "merged_at": "2026-11-12T10:00:00Z",
            "base": {"ref": "main"},
            "merge_commit_sha": self.squash,
            "head": {"sha": self.tip},
        } | fields

    def on_main(self, message: str) -> str:
        """A commit on main that GitHub made: a merge, or an edit on its web page."""
        git(self.local, *BY_GITHUB, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.local, "rev-parse", "HEAD")

    def read(self, listed: dict[str, list[dict[str, Any]]], numbered: dict[int, dict[str, Any]] | None = None) -> Any:
        fetch = pulls.fetcher(str(self.origin), None, self.local)

        def fetching(numbers: list[int]) -> None:
            self.fetched.append(numbers)
            fetch(numbers)

        return pulls.read(self.base, self.local, Fake(listed, numbered or {}), fetching)


@pytest.fixture
def merged(tmp_path: pathlib.Path) -> Merged:
    return Merged(tmp_path)


class TestRead:
    def test_a_squash_merge_carries_what_its_own_commits_allowed(self, merged: Merged) -> None:
        reading = merged.read({merged.squash: [merged.pull()]})
        assert reading.claims == {
            gate.ALLOW: [("tasks/b.txt", "feat: two (#7)"), ("http/a.txt", "feat: one (#7)")],
            gate.HARNESS: [("records more", "feat: two (#7)")],
        }
        assert reading.pulls == {merged.push: None, merged.squash: 7}
        assert (reading.since, reading.head) == (merged.base, merged.squash)
        assert merged.fetched == [[7]]

    def test_main_alone_reads_only_the_push(self, merged: Merged) -> None:
        """What the full comparison read before: the squash message's lines are not trailers."""
        assert gate.claims(gate.ALLOW, merged.base, merged.local) == [("http/pushed.txt", "a push to main")]

    @pytest.mark.parametrize(
        "other",
        [
            {"number": 9, "merge_commit_sha": "0" * 40},
            {"number": 10, "merged_at": None},
            {"number": 11, "base": {"ref": "production"}},
        ],
        ids=["merged-as-another-commit", "not-merged", "merged-elsewhere"],
    )
    def test_a_pull_request_not_merged_into_main_as_this_commit_is_not_read(
        self, merged: Merged, other: dict[str, Any]
    ) -> None:
        """Each would fetch, and its trailer be read, were it taken for the pull request merged as this commit."""
        reading = merged.read({merged.squash: [merged.pull(**other, head={"sha": merged.other})]})
        assert reading.claims == {gate.ALLOW: [], gate.HARNESS: []}
        assert reading.pulls == {merged.push: None, merged.squash: None}
        assert merged.fetched == []

    def test_a_push_to_main_has_no_pull_request(self, merged: Merged) -> None:
        reading = merged.read({})
        assert reading.pulls == {merged.push: None, merged.squash: None}
        assert reading.claims == {gate.ALLOW: [], gate.HARNESS: []}

    def test_two_pull_requests_merged_as_one_commit_are_not_guessed_between(self, merged: Merged) -> None:
        with pytest.raises(pulls.UnreadableError, match="is the merge of #7, #8"):
            merged.read({merged.squash: [merged.pull(), merged.pull(8)]})

    def test_a_head_that_cannot_be_fetched_fails(self, merged: Merged) -> None:
        git(merged.origin, "update-ref", "-d", "refs/pull/7/head")
        with pytest.raises(pulls.UnreadableError, match="git fetch refs/pull/7/head"):
            merged.read({merged.squash: [merged.pull()]})

    def test_a_head_the_fetch_did_not_bring_fails(self, merged: Merged) -> None:
        """GitHub's head and the ref it serves disagree: the commits read would not be the ones merged."""
        with pytest.raises(pulls.UnreadableError, match="is not here after fetching"):
            merged.read({merged.squash: [merged.pull(head={"sha": "1" * 40})]})

    def test_an_api_that_cannot_be_read_fails(self, merged: Merged) -> None:
        refusing = Refusing(pulls.UnreadableError("403 rate limit exceeded"))
        with pytest.raises(pulls.UnreadableError, match="rate limit"):
            pulls.read(merged.base, merged.local, refusing, merged.fetched.append)

    def test_a_rebase_merge_before_its_last_commit_is_read_as_itself(self, merged: Merged) -> None:
        """GitHub commits each commit a rebase merge makes, and names the pull request for each, merged as the last."""
        rebased = merged.on_main("feat: rebased\n\nBehaviour-Allow: http/rebased.txt")
        reading = merged.read({rebased: [merged.pull(31, merge_commit_sha="2" * 40)]})
        assert reading.pulls[rebased] is None
        assert reading.claims[gate.ALLOW] == []

    def test_a_pull_request_whose_commits_are_mains_own_carries_nothing_more(self, merged: Merged) -> None:
        """Its head was pushed to main before it merged: what its commits allowed, main's own trailers say."""
        reading = merged.read({merged.squash: [merged.pull(head={"sha": merged.push})]})
        assert reading.pulls == {merged.push: None, merged.squash: 7}
        assert reading.claims == {gate.ALLOW: [], gate.HARNESS: []}

    def test_a_merge_on_main_is_one_commit_and_its_branch_is_not_walked(self, merged: Merged) -> None:
        git(merged.origin, "checkout", "-q", "--detach", merged.base)
        feature = commit(merged.origin, "feat: twelve\n\nBehaviour-Allow: http/twelve.txt", {"t": "1"})
        git(merged.origin, "update-ref", "refs/pull/12/head", feature)
        for key, value in (("user.email", "t@example.org"), ("user.name", "t"), ("commit.gpgsign", "false")):
            git(merged.local, "config", key, value)
        git(merged.local, "fetch", "-q", str(merged.origin), "refs/pull/12/head")
        git(merged.local, "merge", "-q", "--no-ff", "FETCH_HEAD", "-m", "Merge pull request #12")
        merge = git(merged.local, "rev-parse", "HEAD")
        reading = merged.read({merge: [merged.pull(12, merge_commit_sha=merge, head={"sha": feature})]})
        assert reading.pulls == {merged.push: None, merged.squash: None, merge: 12}
        assert reading.claims[gate.ALLOW] == [("http/twelve.txt", "feat: twelve (#12)")]


class TestNotLinkedYet:
    """GitHub links a merge to its pull request a little after it makes it. Only a subject ending in `(#N)`
    says a commit is one: who committed it does not, since GitHub commits an edit made on its web page to
    main as well, and main is not protected."""

    def test_an_edit_on_githubs_web_page_is_a_push(self, merged: Merged) -> None:
        edited = merged.on_main("chore: mark several requirements as done\n\nBehaviour-Allow: http/edited.txt")
        reading = merged.read({})
        assert reading.pulls[edited] is None
        assert reading.claims[gate.ALLOW] == []

    def test_an_edit_linked_only_to_a_pull_request_merged_elsewhere_is_a_push(self, merged: Merged) -> None:
        edited = merged.on_main("Fix link formatting in DESIGN.md")
        production = merged.pull(359, base={"ref": "production"}, merge_commit_sha=edited)
        reading = merged.read({edited: [production]})
        assert reading.pulls[edited] is None

    def test_a_squash_merge_not_listed_yet_is_found_by_its_number(self, merged: Merged) -> None:
        squash = merged.on_main("feat: three (#30)")
        thirty = merged.pull(30, merge_commit_sha=squash, head={"sha": merged.other})
        reading = merged.read({}, {30: thirty})
        assert reading.pulls[squash] == 30
        assert reading.claims[gate.ALLOW] == [("http/other.txt", "feat: another (#30)")]

    def test_a_squash_merge_github_does_not_say_is_merged_fails_until_it_does(self, merged: Merged) -> None:
        merged.on_main("feat: three (#30)")
        pending = merged.pull(30, merged_at=None, merge_commit_sha="3" * 40, head={"sha": merged.other})
        with pytest.raises(pulls.UnreadableError, match="does not say is merged yet") as raised:
            merged.read({}, {30: pending})
        assert raised.value.again

    @pytest.mark.parametrize(
        "numbered",
        [
            {},
            {
                30: {
                    "number": 30,
                    "merged_at": "2026-11-12T10:00:00Z",
                    "base": {"ref": "main"},
                    "merge_commit_sha": "4" * 40,
                }
            },
        ],
        ids=["an-issue", "merged-as-another-commit"],
    )
    def test_a_subject_naming_what_was_not_merged_as_it_is_a_push(
        self, merged: Merged, numbered: dict[int, dict[str, Any]]
    ) -> None:
        named = merged.on_main("fix: what #30 asked for (#30)")
        reading = merged.read({}, numbered)
        assert reading.pulls[named] is None


class Stack:
    """Pull request 21 was opened on 20's branch, so 21's own line holds 20's commit too, and GitHub lists
    both for it. Main has a push, then the two squash merges, in the order asked."""

    def __init__(self, tmp_path: pathlib.Path, *, twenty_first: bool) -> None:
        self.origin = init(tmp_path / "origin")
        self.base = commit(self.origin, "base", {"a": "1"})
        commit(self.origin, "a push to main\n\nBehaviour-Allow: http/pushed.txt", {"p": "1"})
        git(self.origin, "checkout", "-q", "-b", "stack")
        self.below = commit(self.origin, "feat: a\n\nBehaviour-Allow: http/a.txt", {"x": "1"})
        self.above = commit(self.origin, "feat: b\n\nBehaviour-Allow: http/b.txt", {"y": "1"})
        git(self.origin, "update-ref", "refs/pull/20/head", self.below)
        git(self.origin, "update-ref", "refs/pull/21/head", self.above)
        git(self.origin, "checkout", "-q", "main")
        git(self.origin, "branch", "-q", "-D", "stack")
        merges = [("feat: a (#20)", {"x": "1"}), ("feat: b (#21)", {"y": "1"})]
        for subject, files in merges if twenty_first else merges[::-1]:
            commit(self.origin, subject, files)
        self.merged = {
            int(subject[-3:-1]): sha
            for sha, subject in (
                line.split(" ", 1) for line in git(self.origin, "log", "-2", "--format=%H %s").splitlines()
            )
        }
        self.local = tmp_path / "local"
        git(tmp_path, "clone", "-q", str(self.origin), str(self.local))

    def pull(self, number: int, at: str, base: str = "main") -> dict[str, Any]:
        tip = self.below if number == 20 else self.above
        return {
            "number": number,
            "merged_at": at,
            "base": {"ref": base},
            "merge_commit_sha": self.merged.get(number, "5" * 40),
            "head": {"sha": tip},
        }

    def read(self, twenty: str, twenty_one: str, *also: dict[str, Any]) -> list[tuple[str, str]]:
        """What the two allowed, merged at the times given; GitHub lists both for 20's commit, and `also`."""
        listed = {
            self.merged[20]: [self.pull(20, twenty)],
            self.merged[21]: [self.pull(21, twenty_one)],
            self.below: [self.pull(20, twenty), self.pull(21, twenty_one), *also],
            self.above: [self.pull(21, twenty_one)],
        }
        fetch = pulls.fetcher(str(self.origin), None, self.local)
        return pulls.read(self.base, self.local, Fake(listed), fetch).claims[gate.ALLOW]


EARLY, LATE = "2026-11-12T22:34:22Z", "2026-11-12T23:39:01Z"


class TestStacked:
    """21's own comparison read 20's commit too, but there it allowed only 21's diff; on main it would allow
    the whole night. A commit goes with the pull request merged first."""

    def test_a_stacked_pull_request_does_not_carry_the_one_below(self, tmp_path: pathlib.Path) -> None:
        stack = Stack(tmp_path, twenty_first=True)
        elsewhere = stack.pull(5, "2026-11-01T00:00:00Z", base="production")
        assert stack.read(EARLY, LATE, elsewhere) == [("http/a.txt", "feat: a (#20)"), ("http/b.txt", "feat: b (#21)")]

    def test_merged_first_the_one_above_carries_both(self, tmp_path: pathlib.Path) -> None:
        stack = Stack(tmp_path, twenty_first=False)
        assert stack.read(LATE, EARLY) == [("http/b.txt", "feat: b (#21)"), ("http/a.txt", "feat: a (#21)")]

    def test_merged_in_the_same_second_neither_was_first(self, tmp_path: pathlib.Path) -> None:
        stack = Stack(tmp_path, twenty_first=True)
        assert stack.read(EARLY, EARLY) == [
            ("http/a.txt", "feat: a (#20)"),
            ("http/b.txt", "feat: b (#21)"),
            ("http/a.txt", "feat: a (#21)"),
        ]


class Response(io.BytesIO):
    def __init__(self, body: object, link: str = "") -> None:
        super().__init__(json.dumps(body).encode())
        self.headers = {"Link": link}


def refused(code: int, reason: str, body: bytes) -> Any:
    def refuses(request: urllib.request.Request, timeout: float) -> Response:
        raise urllib.error.HTTPError(request.full_url, code, reason, email.message.Message(), io.BytesIO(body))

    return refuses


class TestApi:
    def test_every_page_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        second = f"{pulls.API}/repositories/1/commits/abc/pulls?page=2"
        pages = iter([Response([{"number": 1}], f'<{second}>; rel="next"'), Response([{"number": 2}])])
        asked: list[str] = []

        def answers(request: urllib.request.Request, timeout: float) -> Response:
            asked.append(request.full_url)
            return next(pages)

        monkeypatch.setattr(urllib.request, "urlopen", answers)
        assert pulls.Api("token").pulls_of("abc") == [{"number": 1}, {"number": 2}]
        assert asked[1] == second

    def test_a_rate_limit_says_what_github_said_and_can_pass_later(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            urllib.request, "urlopen", refused(403, "Forbidden", b'{"message": "API rate limit exceeded"}')
        )
        with pytest.raises(pulls.UnreadableError, match=r"403 Forbidden.*API rate limit exceeded") as raised:
            pulls.Api("token").pulls_of("abc")
        assert raised.value.again

    def test_a_refused_token_will_be_refused_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(urllib.request, "urlopen", refused(401, "Unauthorized", b'{"message": "Bad credentials"}'))
        with pytest.raises(pulls.UnreadableError, match="401 Unauthorized") as raised:
            pulls.Api("token").pulls_of("abc")
        assert not raised.value.again

    def test_no_network_fails_and_can_pass_later(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unreachable(request: urllib.request.Request, timeout: float) -> Response:
            raise urllib.error.URLError("no route to host")

        monkeypatch.setattr(urllib.request, "urlopen", unreachable)
        with pytest.raises(pulls.UnreadableError, match="no route to host") as raised:
            pulls.Api("token").pulls_of("abc")
        assert raised.value.again

    def test_a_number_that_is_no_pull_request_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(urllib.request, "urlopen", refused(404, "Not Found", b'{"message": "Not Found"}'))
        assert pulls.Api("token").pull(30) is None

    def test_a_commit_github_does_not_know_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only a number may be missing: a commit GitHub has not got is not one no pull request was merged as."""
        monkeypatch.setattr(urllib.request, "urlopen", refused(404, "Not Found", b'{"message": "Not Found"}'))
        with pytest.raises(pulls.UnreadableError, match="404 Not Found"):
            pulls.Api("token").pulls_of("abc")

    def test_a_pull_request_is_asked_for_by_its_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        asked: list[str] = []

        def answers(request: urllib.request.Request, timeout: float) -> Response:
            asked.append(request.full_url)
            return Response({"number": 30})

        monkeypatch.setattr(urllib.request, "urlopen", answers)
        assert pulls.Api("token").pull(30) == {"number": 30}
        assert asked == [f"{pulls.API}/repos/{pulls.REPOSITORY}/pulls/30"]


class TestApiPages:
    def test_a_next_page_on_another_host_is_not_asked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The token goes with every page: a page elsewhere would be handed it."""
        asked: list[str] = []

        def answers(request: urllib.request.Request, timeout: float) -> Response:
            asked.append(request.full_url)
            assert len(asked) == 1, f"asked {request.full_url} as well"
            return Response([{"number": 1}], '<https://elsewhere.example/next>; rel="next"')

        monkeypatch.setattr(urllib.request, "urlopen", answers)
        with pytest.raises(pulls.UnreadableError, match="which is not"):
            pulls.Api("token").pulls_of("abc")


class TestFetch:
    """The repository is private: a fetch goes with the token, or fails and says it had none."""

    def test_the_token_goes_to_git_as_a_header(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        given: list[dict[str, str]] = []

        def runs(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            given.append(kwargs["env"])
            return subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr(subprocess, "run", runs)
        pulls.fetcher("https://example.org/r.git", "not-a-real-token", tmp_path)([7])
        basic = base64.b64encode(b"x-access-token:not-a-real-token").decode()
        assert given[0]["GIT_CONFIG_KEY_0"] == f"http.{pulls.SERVER}/.extraheader"
        assert given[0]["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: basic {basic}"
        assert given[0]["GIT_CONFIG_COUNT"] == "1"

    def test_a_fetch_without_a_token_that_fails_says_so(self, merged: Merged) -> None:
        with pytest.raises(
            pulls.UnreadableError, match=r"git fetch refs/pull/99/head: .*\(no token was given to git\)"
        ):
            pulls.fetcher(str(merged.origin), None, merged.local)([99])


class TestMain:
    """A night that cannot ask GitHub fails, and leaves no reading for the comparison to take."""

    @pytest.fixture
    def stale(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
        out = tmp_path / "pulls.json"
        out.write_text("{}")
        monkeypatch.setattr(sys, "argv", ["behaviour_pulls.py", "--ref", "main", "--out", str(out)])
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        return out

    def test_without_a_token(
        self, stale: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert pulls.main() == 1
        assert "no token" in capsys.readouterr().err
        assert not stale.exists()

    @pytest.mark.parametrize("again", [True, False])
    def test_when_github_refuses(
        self,
        merged: Merged,
        stale: pathlib.Path,
        again: bool,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The step says whether a later run can pass, for the issue to say whether to run it again."""
        output = stale.parent / "github-output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        monkeypatch.setenv("GH_TOKEN", "token")
        monkeypatch.setattr(pulls, "ROOT", merged.local)
        monkeypatch.setattr(pulls, "Api", lambda token: Refusing(pulls.UnreadableError("403 rate limit", again=again)))
        monkeypatch.setattr(sys, "argv", ["behaviour_pulls.py", "--ref", merged.base, "--out", str(stale)])
        assert pulls.main() == 1
        err = capsys.readouterr().err
        assert "Cannot read what the pull requests merged as these commits allowed: 403 rate limit" in err
        assert "Not compared" in err
        assert not stale.exists()
        assert output.read_text() == f"again={'true' if again else 'false'}\n"

    def test_a_reading_is_written_with_its_range(
        self, merged: Merged, stale: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "token")
        monkeypatch.setattr(pulls, "ROOT", merged.local)
        monkeypatch.setattr(pulls, "Api", lambda token: Fake({merged.squash: [merged.pull()]}))
        fetcher = pulls.fetcher
        monkeypatch.setattr(pulls, "fetcher", lambda remote, token, cwd: fetcher(str(merged.origin), None, cwd))
        monkeypatch.setattr(sys, "argv", ["behaviour_pulls.py", "--ref", merged.base, "--out", str(stale)])
        assert pulls.main() == 0
        reading = pulls.load(stale)
        assert (reading.since, reading.head) == (merged.base, merged.squash)
        assert reading.claims[gate.ALLOW] == [("tasks/b.txt", "feat: two (#7)"), ("http/a.txt", "feat: one (#7)")]
