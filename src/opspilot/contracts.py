"""OpsPilot pipeline data contracts matching contracts/*.schema.json."""

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class IncidentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(..., description="sha256(alarm_name + floor(detected_at / dedup window))")
    source: Literal["cloudwatch"] = "cloudwatch"
    service: str
    alarm_name: str
    detected_at: str
    window_start: str
    window_end: str
    log_group: str
    repo: Optional[str] = Field(default=None, description="owner/name of the service's source repo")


class SuspectedLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    line: int = Field(..., ge=1)
    function: Optional[str] = None
    commit: Optional[str] = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["log_line", "stack_frame", "commit", "metric"]
    ref: str = Field(..., description="log line id, file:line, or commit sha present in the context bundle")
    claim: str


class RcaResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    classification: Literal[
        "code_defect",
        "config_regression",
        "dependency",
        "resource",
        "insufficient_evidence",
    ]
    severity: Literal["sev1", "sev2", "sev3", "sev4"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    summary: str = Field(..., max_length=600)
    suspected_location: Optional[SuspectedLocation] = None
    evidence: List[EvidenceItem] = Field(..., min_length=1, max_length=10)
    ruled_out: Optional[List[str]] = None
    suggested_fix_strategy: str


class LogLine(BaseModel):
    id: str
    timestamp: str
    message: str


class StackFrame(BaseModel):
    file: str
    line: int
    function: str
    code_context: Optional[str] = None


class StackTraceInfo(BaseModel):
    error_type: str
    error_message: str
    frames: List[StackFrame] = Field(default_factory=list)
    top_frame: Optional[StackFrame] = None


class ContextBundle(BaseModel):
    incident_id: str
    service: str
    log_group: str
    detected_at: str
    log_lines: List[LogLine] = Field(default_factory=list)
    stack_trace: Optional[StackTraceInfo] = None
    repo: Optional[str] = None
    repo_files: dict[str, str] = Field(default_factory=dict)
    recent_commits: List[dict] = Field(default_factory=list)


class TicketRef(BaseModel):
    key: str
    url: str
    incident_id: str


class PrRef(BaseModel):
    branch: str
    base: str = "main"
    repro_test_path: str
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    attempt: int = 1
    status: str = "opened"


class VerificationResult(BaseModel):
    repro_fails_on_base: bool
    suite_passes_on_fix: bool
    verdict: Literal["verified", "failed"]
    details: Optional[str] = None
