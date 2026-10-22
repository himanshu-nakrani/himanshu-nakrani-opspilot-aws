"""GitHub integration for OpsPilot's fix path.

Design rules (see docs/REVIEW_FIXES.md):
- Nothing here ever reports a success it did not observe. Every non-2xx
  response raises a typed ``GitHubError`` so Step Functions can route the
  failure to Notify instead of advertising a PR that does not exist.
- The fix Lambda has no git checkout, so branches are created through the
  GitHub Git Data API (blobs/trees/commits/refs), not ``git push``.
- Only the files the patch policy approved are committed (no ``git add .``).
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class GitHubError(RuntimeError):
    """A GitHub API call did not succeed."""


class GitHubAuthError(GitHubError):
    """No usable GitHub credential is configured."""


class PatchApplyError(RuntimeError):
    """A unified diff does not apply cleanly to the base file content."""


def get_github_token() -> str:
    """Resolve the GitHub token: GITHUB_TOKEN env (local dev) or Secrets Manager (GITHUB_SECRET_ARN).

    The secret may be a raw token string or JSON with a ``token`` field.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    secret_arn = os.environ.get("GITHUB_SECRET_ARN", "").strip()
    if not secret_arn:
        raise GitHubAuthError("Neither GITHUB_TOKEN nor GITHUB_SECRET_ARN is set")
    import boto3  # local import keeps unit tests free of AWS clients

    raw = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn).get("SecretString", "")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            raw = parsed.get("token") or parsed.get("github_token") or ""
    except (json.JSONDecodeError, TypeError):
        pass
    raw = (raw or "").strip()
    if not raw:
        raise GitHubAuthError(f"GitHub secret {secret_arn} is empty")
    return raw


def _headers(token: str) -> Dict[str, str]:
    if not token:
        raise GitHubAuthError("Empty GitHub token")
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }


def _check(resp: httpx.Response, action: str, ok=(200, 201)) -> dict:
    if resp.status_code not in ok:
        raise GitHubError(f"GitHub {action} failed: HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else {}


class GitHubClient:
    """Minimal GitHub REST client. Inject ``http_client`` (e.g. httpx.MockTransport) in tests."""

    def __init__(self, repo: str, token: str, http_client: Optional[httpx.Client] = None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
            raise ValueError(f"Invalid GitHub repo '{repo}'")
        self.repo = repo
        self._headers = _headers(token)
        self._client = http_client or httpx.Client(timeout=15.0)

    def _url(self, path: str) -> str:
        return f"{GITHUB_API}/repos/{self.repo}{path}"

    def _get(self, path: str, action: str, **kw) -> dict:
        return _check(self._client.get(self._url(path), headers=self._headers, **kw), action)

    def _post(self, path: str, payload: dict, action: str, ok=(200, 201)) -> dict:
        return _check(self._client.post(self._url(path), json=payload, headers=self._headers), action, ok)

    def get_file(self, path: str, ref: str) -> str:
        """Return the text content of ``path`` at ``ref``."""
        resp = self._client.get(
            self._url(f"/contents/{path}"),
            params={"ref": ref},
            headers={**self._headers, "Accept": "application/vnd.github.raw+json"},
        )
        if resp.status_code != 200:
            raise GitHubError(f"GitHub get file {path}@{ref} failed: HTTP {resp.status_code}")
        return resp.text

    def get_branch_sha(self, branch: str) -> str:
        return self._get(f"/git/ref/heads/{branch}", f"get ref {branch}")["object"]["sha"]

    def commit_files_to_branch(self, branch: str, base: str, files: Dict[str, str], message: str) -> str:
        """Create (or reset) ``branch`` from ``base`` with exactly ``files`` changed. Returns the commit sha."""
        if not files:
            raise ValueError("No files to commit")
        base_sha = self.get_branch_sha(base)
        base_tree = self._get(f"/git/commits/{base_sha}", "get base commit")["tree"]["sha"]
        tree = self._post(
            "/git/trees",
            {
                "base_tree": base_tree,
                "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in sorted(files.items())],
            },
            "create tree",
        )
        commit = self._post(
            "/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [base_sha]},
            "create commit",
        )
        commit_sha = commit["sha"]
        resp = self._client.post(
            self._url("/git/refs"),
            json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            headers=self._headers,
        )
        if resp.status_code == 422:  # branch exists from a previous attempt: move it
            resp = self._client.patch(
                self._url(f"/git/refs/heads/{branch}"),
                json={"sha": commit_sha, "force": True},
                headers=self._headers,
            )
        _check(resp, f"create/update ref {branch}")
        return commit_sha

    def open_pull_request(self, branch: str, base: str, title: str, body: str) -> Tuple[int, str]:
        """Open a PR, or return the already-open PR for ``branch`` (idempotent on retry)."""
        resp = self._client.post(
            self._url("/pulls"),
            json={"title": title, "head": branch, "base": base, "body": body, "draft": False},
            headers=self._headers,
        )
        if resp.status_code == 422:
            owner = self.repo.split("/")[0]
            existing = self._client.get(
                self._url("/pulls"),
                params={"head": f"{owner}:{branch}", "state": "open"},
                headers=self._headers,
            )
            prs = _check(existing, "list pulls") if existing.status_code == 200 else []
            if prs:
                return prs[0]["number"], prs[0]["html_url"]
        data = _check(resp, "create pull request")
        return data["number"], data["html_url"]

    def add_labels(self, issue_number: int, labels: List[str]) -> None:
        self._post(f"/issues/{issue_number}/labels", {"labels": labels}, "add labels")


def apply_unified_diff(original: str, diff_text: str, path: str) -> str:
    """Apply the hunks for ``path`` in ``diff_text`` to ``original`` (pure Python, no git binary).

    Hunk line counts are ignored; each hunk's context/removed lines must match the
    file exactly (searched near the stated position). Raises PatchApplyError otherwise.
    """
    lines = original.splitlines(keepends=False)
    trailing_nl = original.endswith("\n")
    hunks: List[List[str]] = []
    current_file = None
    hunk: Optional[List[str]] = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            current_file = raw[4:].strip()
            current_file = current_file[2:] if current_file.startswith("b/") else current_file
            hunk = None
            continue
        if raw.startswith("--- "):
            hunk = None
            continue
        if current_file != path:
            continue
        if _HUNK_RE.match(raw):
            hunk = [raw]
            hunks.append(hunk)
        elif hunk is not None and raw[:1] in (" ", "+", "-", ""):
            hunk.append(raw)
    if not hunks:
        raise PatchApplyError(f"Diff contains no hunks for {path}")

    offset = 0
    for h in hunks:
        start = int(_HUNK_RE.match(h[0]).group(1)) - 1
        old = [l[1:] for l in h[1:] if l[:1] in (" ", "-", "")]
        new = [l[1:] for l in h[1:] if l[:1] in (" ", "+", "")]
        guess = max(start + offset, 0)
        pos = None
        for delta in range(0, len(lines) + 1):
            for cand in (guess - delta, guess + delta):
                if 0 <= cand <= len(lines) - len(old) and lines[cand : cand + len(old)] == old:
                    pos = cand
                    break
            if pos is not None:
                break
        if pos is None:
            raise PatchApplyError(f"Hunk '{h[0]}' does not match {path}")
        lines[pos : pos + len(old)] = new
        offset += len(new) - len(old)
    return "\n".join(lines) + ("\n" if trailing_nl else "")


# --- Backwards-compatible thin wrappers (raise instead of faking success) ---

def open_github_pr(repo, branch, base, title, body, token=None, http_client=None) -> Tuple[int, str]:
    return GitHubClient(repo, token or get_github_token(), http_client).open_pull_request(branch, base, title, body)


def mark_pr_needs_human(repo, pr_number, token=None, http_client=None) -> bool:
    GitHubClient(repo, token or get_github_token(), http_client).add_labels(pr_number, ["needs-human"])
    return True
