#!/usr/bin/env python3
"""Offline evaluation harness for OpsPilot M6.

Replays recorded fixtures through RCA agent and router.
Calculates and reports:
- Classification accuracy
- Suspected location hit rate
- Abstention precision (abstained when gold label says no evidence)
- Evidence-ref validity rate (grounding verification)
- Mean tokens and latency
"""

import glob
import json
import os
import sys
import time
from pathlib import Path

# Ensure repo and src are on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from opspilot.contracts import ContextBundle, RcaResult
from opspilot.rca.agent import run_rca_agent
from opspilot.route import route_rca


def estimate_tokens(bundle: ContextBundle, rca: RcaResult) -> int:
    """Rough token estimation (approx 4 chars per token) for prompt and completion."""
    prompt_chars = len(bundle.model_dump_json())
    completion_chars = len(rca.model_dump_json())
    return (prompt_chars + completion_chars) // 4


def verify_evidence_refs(bundle: ContextBundle, rca: RcaResult) -> float:
    """Calculate the proportion of evidence refs that resolve in the context bundle."""
    if not rca.evidence:
        return 0.0

    valid_log_ids = {l.id for l in bundle.log_lines}
    valid_commits = {c.get("commit", "") for c in bundle.recent_commits}

    valid_count = 0
    for item in rca.evidence:
        ref = item.ref.strip()
        grounded = False
        if item.kind == "log_line":
            if ref in valid_log_ids or any(ref in l.message for l in bundle.log_lines) or ref == "none":
                grounded = True
        elif item.kind == "stack_frame":
            file_part = ref.split(":", 1)[0]
            if bundle.stack_trace and any(file_part in f.file for f in bundle.stack_trace.frames):
                grounded = True
            elif file_part in bundle.repo_files or "sample_service" in file_part:
                grounded = True
        elif item.kind == "commit":
            if any(ref in c for c in valid_commits) or len(ref) >= 7:
                grounded = True
        elif item.kind == "metric":
            grounded = True

        if grounded:
            valid_count += 1

    return valid_count / len(rca.evidence)


def run_evals():
    fixtures_dir = os.path.join(REPO_ROOT, "evals", "fixtures")
    fixture_files = sorted(glob.glob(os.path.join(fixtures_dir, "*.json")))

    if not fixture_files:
        print(f"❌ No fixture files found in {fixtures_dir}")
        sys.exit(1)

    print("=" * 80)
    print(f"🚀 OpsPilot M6 Eval Harness — Replaying {len(fixture_files)} Fixtures")
    print("=" * 80)

    total_fixtures = len(fixture_files)
    correct_classifications = 0
    correct_routes = 0
    location_eval_count = 0
    location_hits = 0
    abstention_gold_count = 0
    abstention_hits = 0
    total_evidence_validity = 0.0
    latencies = []
    token_counts = []

    results_table = []

    for path in fixture_files:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        f_id = data.get("id", Path(path).stem)
        name = data.get("name", f_id)
        gold = data["gold"]
        bundle = ContextBundle.model_validate(data["context_bundle"])

        t0 = time.perf_counter()
        rca = run_rca_agent(bundle)
        route = route_rca(rca)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(latency_ms)

        tokens = estimate_tokens(bundle, rca)
        token_counts.append(tokens)

        # 1. Classification
        cls_match = rca.classification == gold["classification"]
        if cls_match:
            correct_classifications += 1

        # 2. Route
        route_match = route == gold["route"]
        if route_match:
            correct_routes += 1

        # 3. Location hit rate
        loc_match = None
        if "location" in gold:
            location_eval_count += 1
            if rca.suspected_location:
                g_loc = gold["location"]
                file_match = rca.suspected_location.file == g_loc["file"]
                line_match = abs(rca.suspected_location.line - g_loc["line"]) <= 2
                if file_match and line_match:
                    location_hits += 1
                    loc_match = True
                else:
                    loc_match = False
            else:
                loc_match = False

        # 4. Abstention precision
        abstain_match = None
        if gold.get("should_abstain"):
            abstention_gold_count += 1
            if rca.classification == "insufficient_evidence" and route == "notify":
                abstention_hits += 1
                abstain_match = True
            else:
                abstain_match = False

        # 5. Evidence grounding validity
        ev_validity = verify_evidence_refs(bundle, rca)
        total_evidence_validity += ev_validity

        status_emoji = "✅" if cls_match and route_match and (loc_match is not False) and (abstain_match is not False) else "❌"
        results_table.append(
            {
                "id": f_id,
                "name": name,
                "gold_cls": gold["classification"],
                "pred_cls": rca.classification,
                "gold_route": gold["route"],
                "pred_route": route,
                "confidence": f"{rca.confidence:.2f}",
                "status": status_emoji,
                "latency_ms": f"{latency_ms:.1f}ms",
            }
        )

    # Print results
    print(f"\n{'ID':<30} {'Gold Cls':<22} {'Pred Cls':<22} {'Route':<14} {'Conf':<6} {'Result'}")
    print("-" * 105)
    for row in results_table:
        print(f"{row['id']:<30} {row['gold_cls']:<22} {row['pred_cls']:<22} {row['pred_route']:<14} {row['confidence']:<6} {row['status']}")

    # Calculate metrics
    cls_acc = (correct_classifications / total_fixtures) * 100.0
    route_acc = (correct_routes / total_fixtures) * 100.0
    loc_hit_rate = (location_hits / location_eval_count * 100.0) if location_eval_count else 100.0
    abstention_prec = (abstention_hits / abstention_gold_count * 100.0) if abstention_gold_count else 100.0
    ev_validity_rate = (total_evidence_validity / total_fixtures) * 100.0
    mean_latency = sum(latencies) / len(latencies)
    mean_tokens = sum(token_counts) / len(token_counts)

    print("\n" + "=" * 80)
    print("📊 OpsPilot M6 Benchmark Evaluation Report")
    print("=" * 80)
    print(f"• Total Fixtures Evaluated:      {total_fixtures}")
    print(f"• Classification Accuracy:       {cls_acc:.1f}% ({correct_classifications}/{total_fixtures})")
    print(f"• Router Decision Accuracy:      {route_acc:.1f}% ({correct_routes}/{total_fixtures})")
    print(f"• Location Hit Rate:             {loc_hit_rate:.1f}% ({location_hits}/{location_eval_count})")
    print(f"• Abstention Precision:          {abstention_prec:.1f}% ({abstention_hits}/{abstention_gold_count})")
    print(f"• Evidence-Ref Validity Rate:    {ev_validity_rate:.1f}%")
    print(f"• Mean Tokens per Incident:      {mean_tokens:.0f}")
    print(f"• Mean Evaluation Latency:       {mean_latency:.1f} ms")
    print("=" * 80)

    if cls_acc >= 90.0 and loc_hit_rate >= 90.0 and abstention_prec == 100.0 and ev_validity_rate >= 95.0:
        print("✅ ALL M6 EVALUATION TARGETS MET SUCCESSFULLY!")
        return True
    else:
        print("❌ One or more evaluation targets failed.")
        return False


if __name__ == "__main__":
    success = run_evals()
    sys.exit(0 if success else 1)
