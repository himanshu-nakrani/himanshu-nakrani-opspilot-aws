"""Knowledge-base document preview and merge ingest."""

from dashboard.app import LOCAL_INCIDENTS_CACHE


def _incident(**overrides):
    row = {
        "incident_id": "inc-kb-1",
        "service": "sample-service",
        "classification": "code_defect",
        "summary": "Missing order raises AttributeError",
        "suspected_location": {"file": "sample_service/app.py", "line": 29, "function": "get_order"},
        "evidence": [{"kind": "stack_frame", "ref": "sample_service/app.py:29", "claim": "order.total on None"}],
        "suggested_fix_strategy": "Return 404 when the order is missing.",
        "patch_diff": "--- a/sample_service/app.py\n+++ b/sample_service/app.py\n+raise HTTPException(404)\n",
        "pr_url": "https://codecommit.example/repositories/opspilot-sample-service/pull-requests/15",
        "pr_branch": "opspilot/OPS-15",
    }
    row.update(overrides)
    return row


def test_document_is_absent_until_a_pull_request_exists():
    from opspilot.knowledge.document import public_knowledge

    assert public_knowledge(_incident(pr_url=None, pr_branch="opspilot/OPS-15")) is None
    assert public_knowledge(_incident(pr_url="opspilot/OPS-15")) is None


def test_document_previews_the_text_that_will_be_ingested():
    from opspilot.knowledge.document import public_knowledge

    doc = public_knowledge(_incident(summary="email ops@example.com saw the failure"))
    assert doc["status"] == "waiting"
    assert doc["error"] is None
    body = doc["body"]
    assert "inc-kb-1" in body
    assert "sample-service" in body
    assert "code_defect" in body
    assert "[REDACTED_EMAIL]" in body
    assert "ops@example.com" not in body
    assert "order.total on None" in body
    assert "sample_service/app.py:29" in body
    assert "get_order" in body
    assert "Return 404 when the order is missing." in body
    assert "raise HTTPException(404)" in body
    assert "pull-requests/15" in body
    assert "opspilot/OPS-15" in body
    assert doc["s3_key"] == "solutions/inc-kb-1.md"


class _S3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


class _Agent:
    def __init__(self, sources=None):
        self.jobs = []
        self.sources = [{"dataSourceId": "ds-1"}] if sources is None else sources

    def list_data_sources(self, **kwargs):
        assert kwargs["knowledgeBaseId"] == "kb-1"
        return {"dataSourceSummaries": self.sources}

    def start_ingestion_job(self, **kwargs):
        self.jobs.append(kwargs)
        return {"ingestionJob": {"ingestionJobId": "job-1"}}


def test_open_pull_request_is_not_uploaded():
    from opspilot.knowledge.ingest import sync_merged_solution

    s3, agent = _S3(), _Agent()
    public, stored = sync_merged_solution(
        _incident(),
        {"status": "opened", "is_merged": False},
        s3_client=s3,
        agent_client=agent,
        bucket="kb-bucket",
        knowledge_base_id="kb-1",
    )
    assert public["status"] == "waiting"
    assert stored == {}
    assert s3.puts == []
    assert agent.jobs == []


def test_merged_pull_request_uploads_the_preview_and_starts_sync():
    from opspilot.knowledge.document import public_knowledge
    from opspilot.knowledge.ingest import sync_merged_solution

    incident = _incident()
    preview = public_knowledge(incident)
    s3, agent = _S3(), _Agent()
    public, stored = sync_merged_solution(
        incident,
        {"status": "merged", "is_merged": True},
        s3_client=s3,
        agent_client=agent,
        bucket="kb-bucket",
        knowledge_base_id="kb-1",
    )
    assert public["status"] == "ingested"
    assert public["body"] == preview["body"]
    assert s3.puts[0]["Bucket"] == "kb-bucket"
    assert s3.puts[0]["Key"] == "solutions/inc-kb-1.md"
    assert s3.puts[0]["Body"] == preview["body"].encode("utf-8")
    assert s3.puts[0]["ServerSideEncryption"] == "AES256"
    assert agent.jobs == [{"knowledgeBaseId": "kb-1", "dataSourceId": "ds-1"}]
    assert stored["knowledge_status"] == "ingested"
    assert stored["knowledge_job_id"] == "job-1"
    assert stored["knowledge_s3_key"] == "solutions/inc-kb-1.md"

    again_s3, again_agent = _S3(), _Agent()
    again, stored_again = sync_merged_solution(
        {**incident, **stored},
        {"status": "merged", "is_merged": True},
        s3_client=again_s3,
        agent_client=again_agent,
        bucket="kb-bucket",
        knowledge_base_id="kb-1",
    )
    assert again["status"] == "ingested"
    assert again["body"] == preview["body"]
    assert stored_again == {}
    assert again_s3.puts == []
    assert again_agent.jobs == []


def test_merge_without_a_bucket_is_a_visible_failure():
    from opspilot.knowledge.ingest import sync_merged_solution

    s3 = _S3()
    public, stored = sync_merged_solution(
        _incident(),
        {"status": "merged", "is_merged": True},
        s3_client=s3,
        agent_client=_Agent(),
        bucket="",
        knowledge_base_id="kb-1",
    )
    assert public["status"] == "failed"
    assert public["error"] == "Knowledge bucket is not configured."
    assert stored["knowledge_status"] == "failed"
    assert s3.puts == []


def test_merge_refuses_a_knowledge_base_with_several_data_sources():
    from opspilot.knowledge.ingest import sync_merged_solution

    s3 = _S3()
    agent = _Agent(sources=[{"dataSourceId": "ds-1"}, {"dataSourceId": "ds-2"}])
    public, stored = sync_merged_solution(
        _incident(),
        {"status": "merged", "is_merged": True},
        s3_client=s3,
        agent_client=agent,
        bucket="kb-bucket",
        knowledge_base_id="kb-1",
    )
    assert public["status"] == "failed"
    assert public["error"] == "The knowledge base must have one data source."
    assert stored["knowledge_status"] == "failed"
    assert s3.puts == []
    assert agent.jobs == []


def test_retrieve_returns_passages_and_stays_empty_without_a_knowledge_base():
    from opspilot.knowledge.retrieve import retrieve_knowledge

    class Retrieve:
        def retrieve(self, **kwargs):
            assert kwargs["knowledgeBaseId"] == "kb-1"
            assert kwargs["retrievalQuery"] == {"text": "missing order"}
            return {
                "retrievalResults": [
                    {
                        "content": {"text": "Return 404 when the order is missing."},
                        "score": 0.91,
                        "location": {"s3Location": {"uri": "s3://kb-bucket/solutions/inc-kb-1.md"}},
                    }
                ]
            }

    found = retrieve_knowledge("missing order", client=Retrieve(), knowledge_base_id="kb-1")
    assert found["passages"][0]["text"] == "Return 404 when the order is missing."
    assert found["passages"][0]["source"] == "s3://kb-bucket/solutions/inc-kb-1.md"
    empty = retrieve_knowledge("missing order", client=Retrieve(), knowledge_base_id="")
    assert empty["passages"] == []
    assert empty["error"] == "Knowledge base is not configured."


def test_managed_knowledge_base_uses_the_managed_s3_connector():
    from opspilot.knowledge.provision import managed_kb_configuration, s3_connector_configuration

    assert managed_kb_configuration() == {
        "type": "MANAGED",
        "managedKnowledgeBaseConfiguration": {"embeddingModelType": "MANAGED"},
    }
    connector = s3_connector_configuration("kb-bucket", "123456789012")
    assert connector["type"] == "MANAGED_KNOWLEDGE_BASE_CONNECTOR"
    connection = connector["managedKnowledgeBaseConnectorConfiguration"]["connectorParameters"]
    assert connection["type"] == "S3"
    assert connection["connectionConfiguration"] == {
        "bucketName": "kb-bucket",
        "bucketOwnerAccountId": "123456789012",
    }


def test_dashboard_shows_the_preview_and_ingests_it_on_merge(monkeypatch):
    import dashboard.app as app_mod
    from fastapi.testclient import TestClient

    inc_id = "inc-kb-dashboard"

    class Merged:
        def get_pull_request_status(self, pr_id):
            assert str(pr_id) == "15"
            return {"status": "merged", "is_merged": True, "pr_number": 15, "pull_request_status": "CLOSED"}

    monkeypatch.setattr(app_mod, "get_scm_client", lambda: Merged())
    s3, agent = _S3(), _Agent()
    monkeypatch.setenv("KNOWLEDGE_BUCKET", "kb-bucket")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "kb-1")
    monkeypatch.delenv("KNOWLEDGE_DATA_SOURCE_ID", raising=False)
    monkeypatch.setattr(app_mod, "get_knowledge_s3_client", lambda: s3)
    monkeypatch.setattr(app_mod, "get_knowledge_agent_client", lambda: agent)

    LOCAL_INCIDENTS_CACHE.insert(0, _incident(incident_id=inc_id, pr_url="https://codecommit.example/pr/15"))
    try:
        with TestClient(app_mod.dashboard_app) as client:
            preview = client.get(f"/api/incidents/{inc_id}").json()["knowledge"]
            assert preview["status"] == "waiting"
            assert "inc-kb-dashboard" in preview["body"]
            merged = client.get(f"/api/incidents/{inc_id}/pr-status").json()
        assert merged["knowledge"]["status"] == "ingested"
        assert merged["knowledge"]["body"] == preview["body"]
        assert s3.puts[0]["Body"] == preview["body"].encode("utf-8")
        assert agent.jobs == [{"knowledgeBaseId": "kb-1", "dataSourceId": "ds-1"}]
    finally:
        LOCAL_INCIDENTS_CACHE[:] = [row for row in LOCAL_INCIDENTS_CACHE if row.get("incident_id") != inc_id]
