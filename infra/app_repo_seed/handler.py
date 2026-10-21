"""Seed the sample-service CodeCommit repo with main, once.

The pipeline cannot be created until the branch exists. A later run leaves an
existing main branch alone, so a stack update does not overwrite app commits.
"""

import os

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = os.path.join(os.path.dirname(__file__), "repo")


def _files():
    found = []
    for dirpath, _, filenames in os.walk(REPO_ROOT):
        for name in filenames:
            if name == ".DS_Store" or name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, REPO_ROOT).replace(os.sep, "/")
            with open(full, "rb") as handle:
                found.append({"filePath": rel, "fileContent": handle.read(), "fileMode": "NORMAL"})
    return found


def on_event(event, _context):
    repo = event["ResourceProperties"]["RepoName"]
    physical = event.get("PhysicalResourceId") or f"seed-{repo}"
    if event["RequestType"] == "Delete":
        return {"PhysicalResourceId": physical}

    client = boto3.client("codecommit")
    try:
        branch = client.get_branch(repositoryName=repo, branchName="main")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "BranchDoesNotExistException":
            raise
        branch = None
    if branch:
        return {
            "PhysicalResourceId": physical,
            "Data": {"CommitId": branch["branch"]["commitId"], "Seeded": "false"},
        }

    commit = client.create_commit(
        repositoryName=repo,
        branchName="main",
        authorName="OpsPilot deploy",
        email="opspilot@noreply.local",
        commitMessage="Initial sample-service source",
        putFiles=_files(),
    )
    return {"PhysicalResourceId": physical, "Data": {"CommitId": commit["commitId"], "Seeded": "true"}}
