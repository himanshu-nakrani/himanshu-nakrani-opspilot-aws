"""Sentences for incidents the stub cannot turn into a pull request."""

from typing import Any, Dict, Optional


def human_ending_text(item: Dict[str, Any]) -> Optional[str]:
    """Why a person has to finish this incident, or None when a generator or a PR owns it."""
    if item.get("can_raise_pr"):
        return None
    pr_url = item.get("pr_url")
    if isinstance(pr_url, str) and pr_url.strip().lower().startswith(("http://", "https://")):
        return None
    if item.get("status") in {"PR_OPENED", "VERIFIED"}:
        return None

    loc = item.get("suspected_location") or {}
    function = loc.get("function") if isinstance(loc, dict) else ""
    text = " ".join(
        part
        for part in (
            function or "",
            item.get("summary") or "",
            item.get("classification") or "",
            item.get("suggested_fix_strategy") or "",
            item.get("alarm_name") or "",
        )
        if part
    ).lower()

    if function in {"inventory", "_open_inventory_connection"} or (
        "inventory" in text and ("timeout" in text or "timed out" in text)
    ):
        return "A person has to handle this. The inventory lookup hits a database timeout."
    if function == "export_report" or ("export" in text and ("memory" in text or "oom" in text)):
        return "A person has to handle this. The export runs out of memory."
    if "out of memory" in text or "outofmemory" in text or "memoryerror" in text:
        return "A person has to handle this. The process runs out of memory."
    if function == "payment_status" or ("legacy" in text and ("payment" in text or "latency" in text)):
        return "A person has to handle this. The legacy payment provider blocks the request."

    if item.get("status") in {"NOTIFIED", "NEEDS_HUMAN"} or item.get("classification") in {
        "dependency",
        "resource",
        "config_regression",
        "insufficient_evidence",
    }:
        strategy = (item.get("suggested_fix_strategy") or "").strip()
        if strategy and strategy.lower() not in {"n/a", "none", "none proposed."}:
            return f"A person has to handle this. {strategy}"
        return "A person has to handle this. OpsPilot cannot open a pull request for it."
    if not item.get("patch_diff"):
        return "A person has to handle this. OpsPilot has no patch for it."
    return None
