"""A normal deploy must not import the CodeCommit repo just because it already exists.

CoreStack detaches opspilot-aws when CODECOMMIT_REPO_EXISTS is 1. scripts/deploy.sh
defaults an unset value to 0 and must leave an exported value alone.
"""

import ast
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SH = ROOT / "scripts" / "deploy.sh"


def _env(exported: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CODECOMMIT_REPO_EXISTS", None)
    if exported is not None:
        env["CODECOMMIT_REPO_EXISTS"] = exported
    return env


def _apply(exported: str | None) -> str:
    """Source deploy.sh and run the default helper. Does not run deploy."""
    script = f"""
set -euo pipefail
source {str(DEPLOY_SH)!r}
apply_codecommit_repo_exists_default
printf '%s' "${{CODECOMMIT_REPO_EXISTS-UNSET}}"
"""
    # pathlib-safe quoting: bash needs a quoted path, and !r is Python repr (single quotes).
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=_env(exported),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_deploy_sh_parses():
    result = subprocess.run(["bash", "-n", str(DEPLOY_SH)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_sourcing_does_not_run_a_command_or_assign_one():
    script = f"""
set -euo pipefail
source {str(DEPLOY_SH)!r}
printf 'SOURCED_OK'
"""
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=_env(None),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "SOURCED_OK"


def test_unset_defaults_to_zero():
    assert _apply(None) == "0"


def test_exported_zero_stays_zero():
    assert _apply("0") == "0"


def test_exported_one_stays_one():
    assert _apply("1") == "1"


def test_script_never_sets_the_flag_to_one():
    text = DEPLOY_SH.read_text()
    assert "CODECOMMIT_REPO_EXISTS=1" not in text
    assert "repo-status" not in text
    guard = text.index('if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then')
    source_at = text.index("source .env.deploy", guard)
    default_at = text.index("\napply_codecommit_repo_exists_default\n", source_at)
    deploy_at = text.index("\n  deploy)", default_at)
    assert guard < source_at < default_at < deploy_at
    resolve_at = text.index("resolve_env() {")
    resolve_body = text[resolve_at:guard]
    assert "apply_codecommit_repo_exists_default" in resolve_body
    assert "repo-status" not in resolve_body


def test_help_does_not_deploy():
    """Executing the script still reaches a command, and help does not deploy."""
    result = subprocess.run(
        ["bash", str(DEPLOY_SH), "help"],
        cwd=ROOT,
        env=_env(None),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "bash scripts/deploy.sh" in result.stdout
    assert "Preflight" not in result.stdout
    assert "Deploy OpsPilotCoreStack" not in result.stdout


def _flag_after_help(exported: str | None, tmp_path: Path) -> str:
    """Run `deploy.sh help` (no deploy) and read the flag the process actually left set."""
    out = tmp_path / "flag"
    trap = tmp_path / "trap.sh"
    trap.write_text(
        "trap 'printf %s \"${CODECOMMIT_REPO_EXISTS-UNSET}\" > \"$FLAG_OUT\"' EXIT\n"
    )
    env = _env(exported)
    env["BASH_ENV"] = str(trap)
    env["FLAG_OUT"] = str(out)
    result = subprocess.run(
        ["bash", str(DEPLOY_SH), "help"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Deploy OpsPilotCoreStack" not in result.stdout
    return out.read_text()


def test_executed_help_defaults_unset_to_zero(tmp_path: Path):
    assert _flag_after_help(None, tmp_path) == "0"


def test_executed_help_keeps_exported_zero(tmp_path: Path):
    assert _flag_after_help("0", tmp_path) == "0"


def test_executed_help_keeps_exported_one(tmp_path: Path):
    assert _flag_after_help("1", tmp_path) == "1"


def test_core_stack_imports_only_for_explicit_one(monkeypatch):
    source = (ROOT / "infra" / "core_stack.py").read_text()
    assert "if should_import_codecommit_repo():" in source
    assert source.count('os.environ.get("CODECOMMIT_REPO_EXISTS")') == 1
    # Deprecated exports stay. Importing the repo must not drop them.
    assert "self.export_value(self.jira_secret.secret_arn)" in source
    assert "self.export_value(self.github_secret.secret_arn)" in source
    assert "self.export_value(self.source_repo.repository_arn)" in source
    assert "self.export_value(self.source_repo.repository_name)" in source
    assert "self.export_value(self.source_repo.repository_clone_url_http)" in source

    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "should_import_codecommit_repo"
    )
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"os": os}
    exec(compile(module, "infra/core_stack.py", "exec"), namespace)
    should_import = namespace["should_import_codecommit_repo"]

    monkeypatch.delenv("CODECOMMIT_REPO_EXISTS", raising=False)
    assert should_import() is False
    monkeypatch.setenv("CODECOMMIT_REPO_EXISTS", "0")
    assert should_import() is False
    monkeypatch.setenv("CODECOMMIT_REPO_EXISTS", "1")
    assert should_import() is True
