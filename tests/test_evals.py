"""Unit tests for M6 offline evaluation harness."""

from evals.run_evals import run_evals


def test_eval_harness_fixtures():
    """Verify that all recorded fixtures replay successfully through the eval harness."""
    assert run_evals() is True
