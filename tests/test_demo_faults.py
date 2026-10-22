"""Region selection for the live fault script. No AWS calls."""

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("demo_faults", ROOT / "scripts" / "demo_faults.py")
demo_faults = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo_faults)


def test_availability_zone_is_trimmed_to_a_region(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1a")
    assert demo_faults.resolve_region() == "us-east-1"


def test_missing_region_uses_instance_metadata(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr(demo_faults, "_imds_region", lambda: "eu-west-1")
    assert demo_faults.resolve_region() == "eu-west-1"


def test_ensure_login_skips_aws_login_when_the_session_works(monkeypatch):
    monkeypatch.setattr(demo_faults, "_caller_identity_ok", lambda: True)
    calls = []
    monkeypatch.setattr(demo_faults.subprocess, "call", lambda cmd: calls.append(cmd) or 0)
    demo_faults.ensure_login()
    assert calls == []


def test_ensure_login_starts_ec2_login_when_the_session_is_expired(monkeypatch):
    state = {"ok": False}

    def identity():
        return state["ok"]

    def call(cmd):
        assert cmd[0] == "bash"
        assert cmd[1].endswith("ec2.sh")
        assert cmd[-1] == "login"
        state["ok"] = True
        return 0

    monkeypatch.setattr(demo_faults, "_caller_identity_ok", identity)
    monkeypatch.setattr(demo_faults.subprocess, "call", call)
    demo_faults.ensure_login()
    assert state["ok"] is True


def test_use_region_exports_both_variables(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "")
    assert demo_faults.use_region() == "us-west-2"
    assert demo_faults.REGION == "us-west-2"
    assert os.environ["AWS_REGION"] == "us-west-2"
    assert os.environ["AWS_DEFAULT_REGION"] == "us-west-2"
