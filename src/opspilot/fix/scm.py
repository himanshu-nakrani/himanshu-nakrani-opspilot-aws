"""Source-control provider selection for OpsPilot.

AWS CodeCommit is the default and the only provider the CDK stacks deploy
(IAM-authenticated, no external tokens). ``SCM_PROVIDER=github`` keeps the
legacy GitHub client usable for local development only.
"""

import os
from typing import Any


def provider() -> str:
    return os.environ.get("SCM_PROVIDER", "codecommit").strip().lower() or "codecommit"


def repo_name() -> str:
    if provider() == "github":
        return os.environ.get("GITHUB_REPO", "himanshu-nakrani/opspilot-aws")
    from opspilot.fix.codecommit import default_repo_name

    return default_repo_name()


def get_scm_client() -> Any:
    """Return a client exposing get_file / get_branch_sha / commit_files_to_branch /
    open_pull_request / mark_needs_human for the configured provider.

    The CodeCommit client also exposes get_pull_request_status.
    """
    if provider() == "github":
        from opspilot.fix.git_ops import GitHubClient, get_github_token

        return GitHubClient(repo_name(), get_github_token())
    if provider() != "codecommit":
        raise ValueError(f"Unsupported SCM_PROVIDER '{provider()}' (expected 'codecommit' or 'github')")
    from opspilot.fix.codecommit import CodeCommitClient

    return CodeCommitClient(repo_name())
