"""CodeCommit SCM client: IAM/boto3-only fix path (branch, commit, PR, needs-human)."""

import pytest

from opspilot.fix.codecommit import (
    CodeCommitClient,
    CodeCommitError,
    NEEDS_HUMAN_PREFIX,
    parse_pr_console_url,
    pr_console_url,
)
from opspilot.fix import scm


class _ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeCodeCommit:
    """In-memory stand-in for boto3.client('codecommit')."""

    def __init__(self):
        self.branches = {"main": "base000"}
        self.files = {("base000", "sample_service/app.py"): b"print('base')\n"}
        self.commits = {"base000": {"commitId": "base000", "parents": [], "message": "init\n", "author": {"name": "dev"}}}
        self.prs = {}
        self.calls = []
        self.comments = []

    def _rec(self, name, kw):
        self.calls.append((name, kw))
        assert kw.get("repositoryName", "opspilot-aws") == "opspilot-aws"

    def get_branch(self, **kw):
        self._rec("get_branch", kw)
        if kw["branchName"] not in self.branches:
            raise _ClientError("BranchDoesNotExistException")
        return {"branch": {"commitId": self.branches[kw["branchName"]]}}

    def get_file(self, **kw):
        self._rec("get_file", kw)
        sha = self.branches.get(kw["commitSpecifier"], kw["commitSpecifier"])
        return {"fileContent": self.files[(sha, kw["filePath"])]}

    def create_branch(self, **kw):
        self._rec("create_branch", kw)
        if kw["branchName"] in self.branches:
            raise _ClientError("BranchNameExistsException")
        self.branches[kw["branchName"]] = kw["commitId"]

    def delete_branch(self, **kw):
        self._rec("delete_branch", kw)
        del self.branches[kw["branchName"]]

    def create_commit(self, **kw):
        self._rec("create_commit", kw)
        assert self.branches[kw["branchName"]] == kw["parentCommitId"]
        sha = f"c{len(self.commits):06d}"
        self.commits[sha] = {"commitId": sha, "parents": [kw["parentCommitId"]], "message": kw["commitMessage"], "author": {"name": kw["authorName"]}}
        for f in kw["putFiles"]:
            self.files[(sha, f["filePath"])] = f["fileContent"]
        self.branches[kw["branchName"]] = sha
        return {"commitId": sha}

    def list_pull_requests(self, **kw):
        self._rec("list_pull_requests", kw)
        return {"pullRequestIds": [k for k, v in self.prs.items() if v["pullRequestStatus"] == "OPEN"]}

    def get_pull_request(self, pullRequestId):
        return {"pullRequest": self.prs[pullRequestId]}

    def create_pull_request(self, title, description, targets):
        pid = str(len(self.prs) + 1)
        src, dst = targets[0]["sourceReference"], targets[0]["destinationReference"]
        t = {"repositoryName": targets[0]["repositoryName"], "sourceReference": f"refs/heads/{src}",
             "destinationReference": f"refs/heads/{dst}", "sourceCommit": self.branches[src],
             "destinationCommit": self.branches[dst]}
        self.prs[pid] = {"pullRequestId": pid, "title": title, "description": description, "pullRequestStatus": "OPEN", "pullRequestTargets": [t]}
        return {"pullRequest": self.prs[pid]}

    def update_pull_request_title(self, pullRequestId, title):
        self.prs[pullRequestId]["title"] = title

    def post_comment_for_pull_request(self, **kw):
        self._rec("post_comment_for_pull_request", kw)
        self.comments.append(kw)

    def get_commit(self, **kw):
        return {"commit": self.commits[kw["commitId"]]}

    def get_differences(self, **kw):
        after, path = kw["afterCommitSpecifier"], kw.get("afterPath")
        before = kw.get("beforeCommitSpecifier")
        diffs = [{"changeType": "M", "afterBlob": {"path": p}} for (sha, p) in self.files
                 if sha == after and (path is None or p == path)
                 and (before is None or self.files.get((before, p)) != self.files[(sha, p)])]
        return {"differences": diffs}


@pytest.fixture
def cc():
    fake = FakeCodeCommit()
    return CodeCommitClient("opspilot-aws", client=fake, region="us-east-1"), fake


def test_commit_creates_branch_with_only_given_files(cc):
    client, fake = cc
    sha = client.commit_files_to_branch("opspilot/OPS-1", "main", {"sample_service/app.py": "fixed\n", "tests/t.py": "x\n"}, "fix")
    assert fake.branches["opspilot/OPS-1"] == sha
    put = [c for c in fake.calls if c[0] == "create_commit"][0][1]["putFiles"]
    assert sorted(f["filePath"] for f in put) == ["sample_service/app.py", "tests/t.py"]
    assert client.get_file("sample_service/app.py", "opspilot/OPS-1") == "fixed\n"
    assert fake.branches["main"] == "base000"  # base untouched


def test_retry_resets_existing_branch_and_reuses_open_pr(cc):
    client, fake = cc
    client.commit_files_to_branch("opspilot/OPS-1", "main", {"a.py": "1\n"}, "fix")
    n1, url1 = client.open_pull_request("opspilot/OPS-1", "main", "t", "b")
    client.commit_files_to_branch("opspilot/OPS-1", "main", {"a.py": "2\n"}, "fix again")
    n2, url2 = client.open_pull_request("opspilot/OPS-1", "main", "t", "b")
    assert (n1, url1) == (n2, url2) and len(fake.prs) == 1
    assert any(c[0] == "delete_branch" for c in fake.calls)
    assert "codecommit/repositories/opspilot-aws/pull-requests/1" in url1


def test_mark_needs_human_prefixes_title_once_and_comments(cc):
    client, fake = cc
    client.commit_files_to_branch("opspilot/OPS-2", "main", {"a.py": "1\n"}, "fix")
    n, _ = client.open_pull_request("opspilot/OPS-2", "main", "[OpsPilot] OPS-2", "b")
    client.mark_needs_human(n)
    client.add_labels(n, ["needs-human"])
    assert fake.prs[str(n)]["title"] == NEEDS_HUMAN_PREFIX + "[OpsPilot] OPS-2"
    assert len(fake.comments) == 2 and fake.comments[0]["beforeCommitId"] == "base000"


def test_post_pull_request_comment_does_not_retitle(cc):
    client, fake = cc
    client.commit_files_to_branch("opspilot/OPS-3", "main", {"a.py": "1\n"}, "fix")
    number, _url = client.open_pull_request("opspilot/OPS-3", "main", "Keep this title", "b")
    client.post_pull_request_comment(number, "OpsPilot verification: passed\nTest: sample_service/tests/t.py::test_missing_order_returns_404")
    assert fake.prs[str(number)]["title"] == "Keep this title"
    assert fake.comments[-1]["content"].startswith("OpsPilot verification: passed")
    assert fake.comments[-1]["beforeCommitId"] == "base000"


def test_errors_are_typed(cc):
    client, _ = cc
    with pytest.raises(CodeCommitError):
        client.get_branch_sha("nope")


def test_recent_commits_for_path(cc):
    client, _ = cc
    client.commit_files_to_branch("main2", "main", {"sample_service/app.py": "v2\n"}, "touch app\n\nbody")
    commits = client.recent_commits_for_path("sample_service/app.py", ref="main2")
    assert [c["subject"] for c in commits] == ["touch app", "init"]


def test_pull_request_status_maps_open_merged_closed_and_unknown(cc):
    """Status comes from CodeCommit's pullRequestStatus and isMerged. Unknown values pass through."""
    client, fake = cc
    client.commit_files_to_branch("opspilot/OPS-9", "main", {"a.py": "1\n"}, "fix")
    number, _url = client.open_pull_request("opspilot/OPS-9", "main", "t", "b")
    opened = client.get_pull_request_status(number)
    assert opened["status"] == "open"
    assert opened["pull_request_status"] == "OPEN"
    assert opened["is_merged"] is None

    pr = fake.prs[str(number)]
    pr["pullRequestStatus"] = "CLOSED"
    pr["pullRequestTargets"][0]["mergeMetadata"] = {"isMerged": False}
    closed = client.get_pull_request_status(number)
    assert closed["status"] == "closed" and closed["is_merged"] is False

    pr["pullRequestTargets"][0]["mergeMetadata"] = {"isMerged": True}
    merged = client.get_pull_request_status(number)
    assert merged["status"] == "merged" and merged["is_merged"] is True and merged["pull_request_status"] == "CLOSED"

    pr["pullRequestStatus"] = "PENDING"
    raw = client.get_pull_request_status(number)
    assert raw["status"] == "PENDING" and raw["pull_request_status"] == "PENDING"

    pr.pop("pullRequestStatus")
    with pytest.raises(CodeCommitError, match="no pullRequestStatus"):
        client.get_pull_request_status(number)


def test_parse_pr_console_url_round_trip():
    url = pr_console_url("opspilot-sample-service", 42, "us-east-1")
    assert parse_pr_console_url(url) == ("opspilot-sample-service", "42", "us-east-1")
    assert parse_pr_console_url("https://codecommit.example/pr/9") == (None, None, None)


def test_codecommit_client_uses_default_region_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    created = {}

    class _Boto:
        @staticmethod
        def client(service, region_name=None):
            created["service"] = service
            created["region_name"] = region_name
            return FakeCodeCommit()

    monkeypatch.setitem(__import__("sys").modules, "boto3", _Boto)
    client = CodeCommitClient("opspilot-aws")
    assert created == {"service": "codecommit", "region_name": "us-east-1"}
    assert client.region == "us-east-1"


def test_invalid_repo_name_rejected():
    with pytest.raises(ValueError):
        CodeCommitClient("owner/repo", client=FakeCodeCommit())


def test_scm_defaults_to_codecommit(monkeypatch):
    monkeypatch.delenv("SCM_PROVIDER", raising=False)
    monkeypatch.setenv("CODECOMMIT_REPO", "opspilot-aws")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    assert scm.provider() == "codecommit" and scm.repo_name() == "opspilot-aws"
    assert isinstance(scm.get_scm_client(), CodeCommitClient)
    monkeypatch.setenv("SCM_PROVIDER", "svn")
    with pytest.raises(ValueError):
        scm.get_scm_client()


def test_propose_fix_end_to_end_on_codecommit(cc, sample_inputs):
    """The real fix agent drives CodeCommit: branch + commit + PR, then needs-human."""
    from opspilot.fix import agent

    client, fake = cc
    with open("sample_service/app.py", "rb") as f:
        fake.files[("base000", "sample_service/app.py")] = f.read()
    rca, ticket = sample_inputs
    pr = agent.propose_fix(rca, ticket, github=client)
    assert pr.pr_number == 1 and fake.branches[pr.branch] != "base000"
    assert "codecommit" in pr.pr_url
    out = agent.mark_needs_human_handler({"pr": pr.model_dump()}, github=client)
    assert out["status"] == "needs_human" and fake.prs["1"]["title"].startswith(NEEDS_HUMAN_PREFIX)
