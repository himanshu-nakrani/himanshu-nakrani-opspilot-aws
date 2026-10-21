"""Lambda asset bundling that works with or without Docker.

CDK tries ``local`` first and falls back to the Docker image only if it returns
False. The local path installs Linux/CPython 3.12 wheels explicitly
(``--platform manylinux2014_x86_64 --python-version 3.12 --only-binary``), so a
build host running a different Python or OS still produces a package that
imports on the Lambda runtime. Plain ``pip install -t`` on the host would pull
host-ABI wheels (e.g. a cp314 pydantic_core) that crash on cold start.
"""

import os
import shutil
import subprocess
import sys
from typing import Iterable, List, Tuple

import aws_cdk as cdk
import jsii
from aws_cdk import aws_lambda as lambda_

LAMBDA_PLATFORM_ARGS = [
    "--platform", "manylinux2014_x86_64",
    "--implementation", "cp",
    "--python-version", "3.12",
    "--only-binary=:all:",
]


def _install_cmds(requirements: str, output_dir: str) -> List[List[str]]:
    cmds = []
    if shutil.which("uv"):
        cmds.append([
            "uv", "pip", "install", "--no-cache", "-r", requirements, "--target", output_dir,
            "--python-platform", "x86_64-manylinux2014", "--python-version", "3.12", "--only-binary", ":all:",
        ])
    cmds.append([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", requirements,
                 "-t", output_dir, *LAMBDA_PLATFORM_ARGS])
    return cmds


@jsii.implements(cdk.ILocalBundling)
class LocalPipBundling:
    """Install ``requirements`` for Lambda and copy ``(src, dest)`` dirs into the asset."""

    def __init__(self, repo_root: str, requirements: str, copies: Iterable[Tuple[str, str]]) -> None:
        self.repo_root = repo_root
        self.requirements = requirements
        self.copies = list(copies)

    def try_bundle(self, output_dir: str, options: cdk.BundlingOptions) -> bool:
        req = os.path.join(self.repo_root, self.requirements)
        for cmd in _install_cmds(req, output_dir):
            try:
                if subprocess.run(cmd, capture_output=True, text=True).returncode == 0:
                    break
            except FileNotFoundError:
                continue
        else:
            return False  # let CDK fall back to Docker
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "tests")
        for src, dest in self.copies:
            target = os.path.join(output_dir, dest)
            if os.path.exists(target):
                shutil.rmtree(target)
            shutil.copytree(os.path.join(self.repo_root, src), target, ignore=ignore)
        return True


def python_lambda_code(repo_root: str, requirements: str, copies: Iterable[Tuple[str, str]],
                       include: Iterable[str]) -> lambda_.Code:
    """Asset with deps from ``requirements`` plus copied source dirs; local first, Docker fallback."""
    copies = list(copies)
    exclude = ["*"]
    for path in [requirements, *include]:
        exclude += [f"!{path}", f"!{path}/**"]
    docker_cmd = f"pip install --no-cache-dir -r {requirements} -t /asset-output" + "".join(
        f" && cp -r {src} /asset-output/{dest}" for src, dest in copies
    )
    return lambda_.Code.from_asset(
        repo_root,
        exclude=exclude,
        bundling=cdk.BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            local=LocalPipBundling(repo_root, requirements, copies),
            command=["bash", "-c", docker_cmd],
        ),
    )
