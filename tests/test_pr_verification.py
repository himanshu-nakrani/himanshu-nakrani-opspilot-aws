"""Verify-build and storefront deploy status, with fake AWS clients."""

from opspilot.contracts import EvidenceItem, PrRef, RcaResult, SuspectedLocation
from opspilot.deploy.pipeline import pipeline_view_url, refresh_deploy
from opspilot.verify.pr_check import begin_pr_verification, refresh_verification


def _rca():
    return RcaResult(
        incident_id="inc-verify",
        classification="code_defect",
        severity="sev2",
        confidence=0.9,
        summary="missing order",
        suspected_location=SuspectedLocation(file="sample_service/app.py", line=29, function="get_order"),
        evidence=[EvidenceItem(kind="stack_frame", ref="sample_service/app.py:29", claim="order.total")],
        suggested_fix_strategy="Return 404.",
    )


def _pr():
    return PrRef(
        branch="opspilot/OPS-1",
        base="main",
        repro_test_path="sample_service/tests/test_opspilot_ops_1.py",
        pr_url="https://codecommit.example/pr/4",
        pr_number=4,
    )


class FakeCodeBuild:
    def __init__(self, build=None, fail_start=False):
        self.fail_start = fail_start
        self.started = []
        self.build = build or {
            "id": "opspilot-verify-fix:1",
            "buildStatus": "IN_PROGRESS",
            "exportedEnvironmentVariables": [],
            "phases": [{"phaseType": "BUILD", "phaseStatus": "IN_PROGRESS"}],
        }

    def start_build(self, **kwargs):
        if self.fail_start:
            raise RuntimeError("AccessDenied")
        self.started.append(kwargs)
        return {"build": self.build}

    def batch_get_builds(self, ids):
        if getattr(self, "fail_read", False):
            raise RuntimeError("throttled")
        assert ids == [self.build["id"]]
        return {"builds": [] if getattr(self, "missing", False) else [self.build]}


def _passed_build():
    return {
        "id": "opspilot-verify-fix:1",
        "buildStatus": "SUCCEEDED",
        "exportedEnvironmentVariables": [
            {"name": "REPRO_FAILS_ON_BASE", "value": "true"},
            {"name": "SUITE_PASSES_ON_FIX", "value": "true"},
        ],
        "phases": [{"phaseType": "BUILD", "phaseStatus": "SUCCEEDED"}],
    }


def test_begin_starts_the_existing_verify_project_on_the_pr_branch(monkeypatch):
    monkeypatch.setenv("CODECOMMIT_REPO", "opspilot-sample-service")
    monkeypatch.delenv("CODECOMMIT_CLONE_URL", raising=False)
    cb = FakeCodeBuild()
    fields = begin_pr_verification(_pr(), _rca(), codebuild_client=cb)
    assert fields["test_status"] == "running"
    assert fields["test_build_id"] == "opspilot-verify-fix:1"
    assert fields["test_error"] is None
    assert "test_missing_order_returns_404" in fields["test_name"]
    started = cb.started[0]
    assert started["projectName"] == "opspilot-verify-fix"
    assert started["sourceVersion"] == "opspilot/OPS-1"
    env = {item["name"]: item["value"] for item in started["environmentVariablesOverride"]}
    assert env["BASE_REF"] == "main"
    assert env["REPRO_TEST"] == "sample_service/tests/test_opspilot_ops_1.py"
    assert env["CODECOMMIT_CLONE_URL"].endswith("/opspilot-sample-service")


def test_begin_records_a_sentence_when_the_build_does_not_start():
    fields = begin_pr_verification(_pr(), _rca(), codebuild_client=FakeCodeBuild(fail_start=True))
    assert fields["test_status"] is None
    assert fields["test_error"] == "The verification build could not be started."
    assert "codebuild" not in fields["test_error"]


def test_refresh_keeps_running_then_comments_once_on_pass():
    cb = FakeCodeBuild()
    comments = []
    inc = begin_pr_verification(_pr(), _rca(), codebuild_client=cb)
    running = refresh_verification(inc, codebuild_client=cb, commenter=comments.append)
    assert running["test_status"] == "running"
    assert comments == []

    cb.build = _passed_build()
    done = refresh_verification({**inc, **running}, codebuild_client=cb, commenter=comments.append)
    assert done["test_status"] == "passed"
    assert done["test_comment_posted"] == "yes"
    assert done["test_error"] is None
    assert comments[0].startswith("OpsPilot verification: passed")
    assert "test_missing_order_returns_404" in comments[0]
    assert "Build status: SUCCEEDED" in comments[0]
    again = refresh_verification({**inc, **done}, codebuild_client=cb, commenter=comments.append)
    assert again["test_comment_posted"] == "yes"
    assert len(comments) == 1


def test_refresh_comments_failure_and_does_not_invent_a_pass_when_unreadable():
    cb = FakeCodeBuild()
    cb.build = {
        "id": "opspilot-verify-fix:1",
        "buildStatus": "FAILED",
        "exportedEnvironmentVariables": [
            {"name": "REPRO_FAILS_ON_BASE", "value": "true"},
            {"name": "SUITE_PASSES_ON_FIX", "value": "false"},
            {"name": "FAILURE_REASON", "value": "suite_fails_on_fix"},
        ],
        "phases": [{"phaseType": "BUILD", "phaseStatus": "FAILED"}],
    }
    comments = []
    inc = {"test_build_id": cb.build["id"], "test_status": "running", "test_name": "sample_service/tests/t.py::test_missing_order_returns_404", "test_comment_posted": ""}
    failed = refresh_verification(inc, codebuild_client=cb, commenter=comments.append)
    assert failed["test_status"] == "failed"
    assert comments[0].startswith("OpsPilot verification: failed")
    assert "suite_fails_on_fix" in comments[0]

    cb.fail_read = True
    unread = refresh_verification({**inc, "test_status": "running"}, codebuild_client=cb, commenter=comments.append)
    assert unread["test_status"] == "running"
    assert unread["test_error"] == "The verification build could not be read."
    assert len(comments) == 1


class FakePipeline:
    def __init__(self, summaries, stages, fail=False):
        self.summaries = summaries
        self.stages = stages
        self.fail = fail
        self.calls = []

    def list_pipeline_executions(self, **kwargs):
        self.calls.append("list")
        if self.fail:
            raise RuntimeError("AccessDenied")
        assert kwargs["pipelineName"] == "opspilot-sample-service"
        return {"pipelineExecutionSummaries": self.summaries}

    def get_pipeline_state(self, **kwargs):
        self.calls.append("state")
        assert kwargs["name"] == "opspilot-sample-service"
        return {"stageStates": self.stages}


def test_open_pull_request_has_not_started_a_deploy():
    pipe = FakePipeline([], [])
    fields = refresh_deploy({}, {"status": "open", "is_merged": False, "error": None}, pipeline_client=pipe)
    assert fields["deploy_status"] == "not_started"
    assert fields["deploy_url"] == pipeline_view_url()
    assert fields["deploy_error"] is None
    assert pipe.calls == []


def test_merged_pull_request_reads_the_matching_execution():
    execution = "exec-1"
    pipe = FakePipeline(
        summaries=[{
            "pipelineExecutionId": execution,
            "status": "InProgress",
            "sourceRevisions": [{"revisionId": "abc123"}],
        }],
        stages=[{
            "stageName": "Deploy",
            "latestExecution": {"pipelineExecutionId": execution, "status": "InProgress"},
        }],
    )
    fields = refresh_deploy(
        {},
        {"status": "merged", "is_merged": True, "merge_commit": "abc123", "error": None},
        pipeline_client=pipe,
    )
    assert fields["deploy_status"] == "in_progress"
    assert fields["deploy_stage"] == "Deploy"
    assert execution in fields["deploy_url"]
    assert "not started" not in fields["deploy_summary"].lower() or "in progress" in fields["deploy_summary"].lower()

    pipe.summaries[0]["status"] = "Succeeded"
    pipe.stages[0]["latestExecution"]["status"] = "Succeeded"
    ok = refresh_deploy({}, {"status": "merged", "is_merged": True, "merge_commit": "abc123", "error": None}, pipeline_client=pipe)
    assert ok["deploy_status"] == "succeeded"

    pipe.summaries[0]["status"] = "Failed"
    failed = refresh_deploy({}, {"status": "merged", "is_merged": True, "merge_commit": "abc123", "error": None}, pipeline_client=pipe)
    assert failed["deploy_status"] == "failed"
    assert failed["deploy_url"].startswith("https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/")


def test_pipeline_read_failure_keeps_the_link_and_does_not_invent_success():
    pipe = FakePipeline([], [], fail=True)
    fields = refresh_deploy(
        {"deploy_status": "in_progress", "deploy_url": pipeline_view_url()},
        {"status": "merged", "is_merged": True, "merge_commit": "abc123", "error": None},
        pipeline_client=pipe,
    )
    assert fields["deploy_status"] == "in_progress"
    assert fields["deploy_error"] == "The pipeline could not be read."
    assert fields["deploy_url"] == pipeline_view_url()
    assert "pipeline" not in fields["deploy_error"] or "could not be read" in fields["deploy_error"]
    assert "/api/" not in fields["deploy_error"]


def test_merged_without_a_commit_does_not_pick_an_execution():
    pipe = FakePipeline(
        summaries=[{"pipelineExecutionId": "other", "status": "Succeeded", "sourceRevisions": [{"revisionId": "zzz"}]}],
        stages=[],
    )
    fields = refresh_deploy({}, {"status": "merged", "is_merged": True, "merge_commit": None, "error": None}, pipeline_client=pipe)
    assert fields["deploy_status"] != "succeeded"
    assert fields["deploy_error"]
    assert pipe.calls == []


def test_raise_pr_attaches_a_running_test_and_later_the_result(monkeypatch):
    import dashboard.app as app_mod
    from fastapi.testclient import TestClient
    from dashboard.app import dashboard_app

    cb = FakeCodeBuild()
    comments = []

    def fake_propose(rca, ticket, **kwargs):
        return _pr()

    class Scm:
        def get_pull_request_status(self, pr_id):
            assert str(pr_id) == "4"
            return {"pr_number": 4, "status": "open", "pull_request_status": "OPEN", "is_merged": False, "merge_commit": None}

        def post_pull_request_comment(self, pr_id, content):
            comments.append(content)

    monkeypatch.setattr(app_mod, "handle_alarm_event", lambda _event: {"status": "started", "incident_id": "inc-live-verify"})
    monkeypatch.setattr(app_mod, "propose_fix", fake_propose)
    monkeypatch.setattr(app_mod, "get_codebuild_client", lambda: cb)
    monkeypatch.setattr(app_mod, "get_scm_client", lambda: Scm())
    with TestClient(dashboard_app) as client:
        inc = client.post("/api/trigger", json={"scenario": "null_order"}).json()["incident"]
        raised = client.post(f"/api/incidents/{inc['incident_id']}/fix-choice", json={"action": "raise_pr"})
        assert raised.status_code == 200, raised.text
        body = raised.json()
        assert body["pr_url"].startswith("https://")
        assert body["test_status"] == "running"
        assert body["deploy_status"] == "not_started"
        assert body["human_ending"] is None
        assert cb.started and cb.started[0]["sourceVersion"] == "opspilot/OPS-1"

        polling = client.get(f"/api/incidents/{inc['incident_id']}/pr-status")
        assert polling.status_code == 200, polling.text
        assert polling.json()["test"]["status"] == "running"
        assert polling.json()["deploy"]["status"] == "not_started"
        assert comments == []

        cb.build = _passed_build()
        done = client.get(f"/api/incidents/{inc['incident_id']}/pr-status")
        assert done.json()["test"]["status"] == "passed"
        assert done.json()["test"]["error"] is None
        assert comments and "passed" in comments[0] and "test_missing_order_returns_404" in comments[0]
        stored = client.get(f"/api/incidents/{inc['incident_id']}").json()
        assert stored["test_status"] == "passed"
        assert stored["deploy_status"] == "not_started"
        assert stored.get("test_summary")
        app_mod.FIX_CHOICES.pop(inc["incident_id"], None)
        app_mod.LOCAL_INCIDENTS_CACHE[:] = [
            row for row in app_mod.LOCAL_INCIDENTS_CACHE if row.get("incident_id") != inc["incident_id"]
        ]
