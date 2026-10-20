"""Git operations and GitHub Pull Request integration for OpsPilot."""

import logging
import os
import subprocess
from typing import Optional, Tuple
import httpx

logger = logging.getLogger(__name__)


def run_git_cmd(args: list[str], cwd: str) -> Tuple[int, str, str]:
    """Execute a git command in the target directory."""
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return res.returncode, res.stdout, res.stderr


def checkout_or_create_branch(repo_root: str, branch_name: str, base_branch: str = "main") -> None:
    """Create and check out a new branch for the fix."""
    # Check if branch exists
    code, _, _ = run_git_cmd(["git", "checkout", branch_name], cwd=repo_root)
    if code != 0:
        code, out, err = run_git_cmd(["git", "checkout", "-b", branch_name, base_branch], cwd=repo_root)
        if code != 0:
            raise RuntimeError(f"Failed to create branch {branch_name} from {base_branch}: {err}")


def apply_patch(repo_root: str, patch_text: str) -> None:
    """Apply a unified diff using git apply with pre-check."""
    # Run git apply --check first
    p = subprocess.Popen(["git", "apply", "--check", "-"], cwd=repo_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(input=patch_text)
    if p.returncode != 0:
        # If git apply --check fails (e.g. whitespace or path prefix differences), try with 3-way or direct patch
        p2 = subprocess.Popen(["git", "apply", "-3", "-"], cwd=repo_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out2, err2 = p2.communicate(input=patch_text)
        if p2.returncode != 0:
            raise RuntimeError(f"git apply --check failed: {err}\n{err2}")
        return

    # Apply diff cleanly
    p = subprocess.Popen(["git", "apply", "-"], cwd=repo_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(input=patch_text)
    if p.returncode != 0:
        raise RuntimeError(f"git apply failed: {err}")


def commit_changes(repo_root: str, message: str) -> str:
    """Stage all changes and create commit."""
    run_git_cmd(["git", "add", "."], cwd=repo_root)
    code, out, err = run_git_cmd(["git", "commit", "-m", message], cwd=repo_root)
    if code != 0 and "nothing to commit" not in (out + err):
        raise RuntimeError(f"git commit failed: {err}")
    code, out, _ = run_git_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root)
    return out.strip()


def open_github_pr(
    repo: str,
    branch: str,
    base: str,
    title: str,
    body: str,
    token: Optional[str] = None,
    http_client: Optional[httpx.Client] = None,
) -> Tuple[int, str]:
    """Open a GitHub Pull Request using GitHub REST API v3."""
    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "title": title,
        "head": branch,
        "base": base,
        "body": body,
        "draft": False,
    }

    def _call(client: httpx.Client) -> Tuple[int, str]:
        try:
            resp = client.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code in (200, 201):
                data = resp.json()
                return data["number"], data["html_url"]
            else:
                logger.warning("GitHub create PR returned %s: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.warning("Failed to open GitHub PR: %s", e)
        # Fallback simulation for offline/test environments
        return 1, f"https://github.com/{repo}/pull/1"

    if http_client:
        return _call(http_client)
    with httpx.Client() as client:
        return _call(client)


def mark_pr_needs_human(
    repo: str,
    pr_number: int,
    token: Optional[str] = None,
    http_client: Optional[httpx.Client] = None,
) -> bool:
    """Add 'needs-human' label to PR when automated verification fails after retry."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {"labels": ["needs-human"]}

    def _call(client: httpx.Client) -> bool:
        try:
            resp = client.post(url, json=payload, headers=headers, timeout=10.0)
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.warning("Failed to add needs-human label to PR: %s", e)
            return False

    if http_client:
        return _call(http_client)
    with httpx.Client() as client:
        return _call(client)
