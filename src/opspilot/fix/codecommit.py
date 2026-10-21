"""AWS CodeCommit integration for OpsPilot's fix path (the default source-control provider).

Everything goes through the CodeCommit API with the Lambda's IAM role (boto3 only):
no git binary, no Git credentials, no third-party token.

Same design rules as the GitHub client it replaces (see docs/REVIEW_FIXES.md):
- Nothing reports a success it did not observe. Every failed call raises a typed
  ``CodeCommitError`` so Step Functions routes the failure to Notify.
- Branches are written with ``CreateCommit`` (only the policy-approved files),
  never ``git add .``.
- Retries are idempotent: a re-run resets the fix branch and reuses the open PR.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
NEEDS_HUMAN_PREFIX = "[needs-human] "
AUTHOR_NAME = "OpsPilot"
AUTHOR_EMAIL = "opspilot@noreply.local"
MAX_COMMIT_FILES = 100  # CodeCommit CreateCommit limit per call


class CodeCommitError(RuntimeError):
    """A CodeCommit API call did not succeed."""


def _code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "") if hasattr(exc, "response") else ""


def default_repo_name() -> str:
    return os.environ.get("CODECOMMIT_REPO", "opspilot-aws").strip()


def pr_console_url(repo: str, pr_id: Any, region: str) -> str:
    return (
        f"https://{region}.console.aws.amazon.com/codesuite/codecommit/repositories/"
        f"{repo}/pull-requests/{pr_id}/details?region={region}"
    )


class CodeCommitClient:
    """Minimal CodeCommit client with the same surface the fix agent uses.

    Inject ``client`` (a boto3 ``codecommit`` client or a fake) in tests.
    """

    def __init__(self, repo: Optional[str] = None, client: Any = None, region: Optional[str] = None):
        repo = (repo or default_repo_name()).strip()
        if not _REPO_RE.fullmatch(repo):
            raise ValueError(f"Invalid CodeCommit repository name '{repo}'")
        self.repo = repo
        if client is None:
            import boto3  # local import keeps unit tests free of AWS clients

            client = boto3.client("codecommit", region_name=region or os.environ.get("AWS_REGION"))
        self._cc = client
        meta_region = getattr(getattr(client, "meta", None), "region_name", None)
        self.region = region or meta_region or os.environ.get("AWS_REGION") or "us-east-1"

    def _call(self, action: str, method: str, **kwargs) -> Dict[str, Any]:
        try:
            return getattr(self._cc, method)(repositoryName=self.repo, **kwargs)
        except Exception as e:  # botocore ClientError / BotoCoreError
            raise CodeCommitError(f"CodeCommit {action} failed: {_code(e) or type(e).__name__}: {e}") from e

    # --- reads -------------------------------------------------------------

    def get_file(self, path: str, ref: str) -> str:
        """Return the text content of ``path`` at ``ref`` (branch name or commit id)."""
        resp = self._call(f"get file {path}@{ref}", "get_file", commitSpecifier=ref, filePath=path)
        content = resp.get("fileContent", b"")
        return content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)

    def get_branch_sha(self, branch: str) -> str:
        return self._call(f"get branch {branch}", "get_branch", branchName=branch)["branch"]["commitId"]

    def recent_commits_for_path(self, path: str, ref: str = "main", limit: int = 3, scan: int = 15) -> List[Dict[str, str]]:
        """Walk first-parent history from ``ref`` (at most ``scan`` commits) and return up to
        ``limit`` commits that touched ``path``. CodeCommit has no path-filtered log API."""
        found: List[Dict[str, str]] = []
        sha: Optional[str] = self.get_branch_sha(ref)
        for _ in range(scan):
            if not sha or len(found) >= limit:
                break
            commit = self._call(f"get commit {sha}", "get_commit", commitId=sha)["commit"]
            parents = commit.get("parents") or []
            diff_kw: Dict[str, Any] = {"afterCommitSpecifier": sha, "afterPath": path}
            if parents:
                diff_kw["beforeCommitSpecifier"] = parents[0]
            touched = self._call(f"get differences {sha}", "get_differences", **diff_kw).get("differences") or []
            if touched:
                found.append({
                    "commit": sha,
                    "subject": (commit.get("message") or "").strip().splitlines()[0] if commit.get("message") else "",
                    "author": (commit.get("author") or {}).get("name", ""),
                })
            sha = parents[0] if parents else None
        return found

    def get_commit_summary(self, sha: str) -> Dict[str, Any]:
        commit = self._call(f"get commit {sha}", "get_commit", commitId=sha)["commit"]
        parents = commit.get("parents") or []
        diff_kw: Dict[str, Any] = {"afterCommitSpecifier": sha}
        if parents:
            diff_kw["beforeCommitSpecifier"] = parents[0]
        diffs = self._call(f"get differences {sha}", "get_differences", **diff_kw).get("differences") or []
        files = []
        for d in diffs[:50]:
            blob = d.get("afterBlob") or d.get("beforeBlob") or {}
            files.append(f"{d.get('changeType', '?')} {blob.get('path', '?')}")
        return {
            "commit": commit.get("commitId", sha),
            "subject": (commit.get("message") or "").strip(),
            "author": (commit.get("author") or {}).get("name", ""),
            "files": files,
        }

    # --- writes ------------------------------------------------------------

    def commit_files_to_branch(self, branch: str, base: str, files: Dict[str, str], message: str) -> str:
        """Create (or reset) ``branch`` from ``base`` with exactly ``files`` changed. Returns the commit id."""
        if not files:
            raise ValueError("No files to commit")
        if len(files) > MAX_COMMIT_FILES:
            raise ValueError(f"CodeCommit allows at most {MAX_COMMIT_FILES} files per commit")
        base_sha = self.get_branch_sha(base)
        try:
            self._cc.create_branch(repositoryName=self.repo, branchName=branch, commitId=base_sha)
        except Exception as e:
            if _code(e) != "BranchNameExistsException":
                raise CodeCommitError(f"CodeCommit create branch {branch} failed: {_code(e) or e}") from e
            # Branch left over from a previous attempt: CodeCommit has no force-update, so recreate it.
            self._call(f"delete branch {branch}", "delete_branch", branchName=branch)
            self._call(f"create branch {branch}", "create_branch", branchName=branch, commitId=base_sha)
        resp = self._call(
            f"create commit on {branch}",
            "create_commit",
            branchName=branch,
            parentCommitId=base_sha,
            authorName=AUTHOR_NAME,
            email=AUTHOR_EMAIL,
            commitMessage=message,
            putFiles=[
                {"filePath": p, "fileMode": "NORMAL", "fileContent": c.encode("utf-8")}
                for p, c in sorted(files.items())
            ],
        )
        commit_id = resp.get("commitId")
        if not commit_id:
            raise CodeCommitError(f"CodeCommit create commit on {branch} returned no commitId")
        return commit_id

    def _find_open_pr(self, branch: str, base: str) -> Optional[Dict[str, Any]]:
        token = None
        while True:
            kw: Dict[str, Any] = {"pullRequestStatus": "OPEN"}
            if token:
                kw["nextToken"] = token
            page = self._call("list pull requests", "list_pull_requests", **kw)
            for pr_id in page.get("pullRequestIds", []):
                pr = self._get_pr(pr_id)
                for t in pr.get("pullRequestTargets", []):
                    if t.get("sourceReference") in (branch, f"refs/heads/{branch}") and t.get(
                        "destinationReference"
                    ) in (base, f"refs/heads/{base}"):
                        return pr
            token = page.get("nextToken")
            if not token:
                return None

    def _get_pr(self, pr_id: Any) -> Dict[str, Any]:
        try:
            return self._cc.get_pull_request(pullRequestId=str(pr_id))["pullRequest"]
        except Exception as e:
            raise CodeCommitError(f"CodeCommit get pull request {pr_id} failed: {_code(e) or e}") from e

    def open_pull_request(self, branch: str, base: str, title: str, body: str) -> Tuple[int, str]:
        """Open a PR, or return the already-open PR for ``branch`` (idempotent on retry)."""
        existing = self._find_open_pr(branch, base)
        if existing:
            pr_id = existing["pullRequestId"]
            return int(pr_id), pr_console_url(self.repo, pr_id, self.region)
        try:
            pr = self._cc.create_pull_request(
                title=title[:150],
                description=body[:10240],
                targets=[{"repositoryName": self.repo, "sourceReference": branch, "destinationReference": base}],
            )["pullRequest"]
        except Exception as e:
            raise CodeCommitError(f"CodeCommit create pull request failed: {_code(e) or e}") from e
        pr_id = pr["pullRequestId"]
        return int(pr_id), pr_console_url(self.repo, pr_id, self.region)

    def mark_needs_human(self, pr_number: int, reason: str = "") -> None:
        """CodeCommit has no labels: prefix the PR title and leave a comment on the PR."""
        pr = self._get_pr(pr_number)
        title = pr.get("title", "")
        if not title.startswith(NEEDS_HUMAN_PREFIX):
            try:
                self._cc.update_pull_request_title(pullRequestId=str(pr_number), title=(NEEDS_HUMAN_PREFIX + title)[:150])
            except Exception as e:
                raise CodeCommitError(f"CodeCommit update pull request title failed: {_code(e) or e}") from e
        target = (pr.get("pullRequestTargets") or [{}])[0]
        before, after = target.get("destinationCommit"), target.get("sourceCommit")
        if before and after:
            self._call(
                "comment on pull request",
                "post_comment_for_pull_request",
                pullRequestId=str(pr_number),
                beforeCommitId=before,
                afterCommitId=after,
                content=reason or "OpsPilot: verification did not pass. Needs a human before merge.",
            )

    def add_labels(self, issue_number: int, labels: List[str]) -> None:
        """GitHub-compatible shim: the only label OpsPilot uses is ``needs-human``."""
        if "needs-human" in labels:
            self.mark_needs_human(issue_number)
