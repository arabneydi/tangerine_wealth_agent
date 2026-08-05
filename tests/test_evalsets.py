"""
Runs the two required trajectory-based evalset scenarios via pytest,
using ADK's AgentEvaluator against the real root_agent.

These tests call the actual configured LLM (Gemini) and therefore
require a valid GOOGLE_API_KEY in the environment -- see README.md.
They are separate from tests/test_tools.py, which covers the
deterministic gate/business logic without any LLM involvement.

Run: pytest tests/test_evalsets.py -v
(Equivalent to running `adk eval` against the same files.)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from google.adk.evaluation.agent_evaluator import AgentEvaluator

EVALSET_DIR = Path(__file__).parent.parent / "evalset"


def _require_api_key():
    """
    IMPORTANT GOTCHA (discovered while building this): if every invocation
    in an eval case errors out (e.g. missing/invalid API key, no network),
    AgentEvaluator.evaluate() produces zero scored results for that eval
    case rather than a failure -- and its internal `assert not failures`
    trivially passes on an empty failures list. In other words: a total
    inference failure can silently look identical to a passing test.

    This guard fails loudly, with a clear reason, before that ambiguity
    can happen, rather than trusting a bare "test passed."
    """
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        pytest.fail(
            "GOOGLE_API_KEY is not set. Skipping would risk a false pass: "
            "ADK's AgentEvaluator silently reports success when every "
            "invocation errors out. Set GOOGLE_API_KEY before running this test."
        )


@pytest.mark.asyncio
async def test_blocked_transfer_unauthenticated():
    """Agent must never call execute_transfer while unverified."""
    _require_api_key()
    await AgentEvaluator.evaluate(
        agent_module="wealth_agent",
        eval_dataset_file_path_or_dir=str(EVALSET_DIR / "blocked_transfer.evalset.json"),
    )


@pytest.mark.asyncio
async def test_successful_transfer_authenticated():
    """Full trajectory: question issued -> correct answer -> transfer executed."""
    _require_api_key()
    await AgentEvaluator.evaluate(
        agent_module="wealth_agent",
        eval_dataset_file_path_or_dir=str(EVALSET_DIR / "successful_transfer.evalset.json"),
    )
