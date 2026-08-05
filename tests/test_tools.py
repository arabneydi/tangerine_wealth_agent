"""
Unit tests for the DB layer, state machine, and tool logic.

These deliberately do NOT invoke the LLM or ADK's runner -- they test
the deterministic parts (state transitions, gating, business logic)
directly, which is exactly the part that must be airtight regardless
of what the model does. The two required ADK evalset scenarios (in
evalset/) separately test the full agent trajectory.
"""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from wealth_agent import state_machine as sm
from wealth_agent.database import init_db
from wealth_agent import tools


class FakeToolContext:
    """Minimal stand-in for ADK's ToolContext; tools only touch .state."""

    def __init__(self):
        self.state = {}


@pytest.fixture(autouse=True)
def fresh_db():
    init_db(reset=True)
    yield


def test_portfolio_balance_success():
    ctx = FakeToolContext()
    result = tools.get_portfolio_balance("user_001", ctx)
    assert result["status"] == "success"
    assert result["checking_balance"] == 2500.00


def test_portfolio_balance_unknown_user():
    ctx = FakeToolContext()
    result = tools.get_portfolio_balance("nope", ctx)
    assert result["status"] == "error"


def test_transfer_blocked_when_unverified():
    """The core security invariant: no transfer without VERIFIED state."""
    ctx = FakeToolContext()
    result = tools.execute_transfer("user_001", "checking", "savings", 100, ctx)
    assert result["status"] == "error"
    assert result["reason"] == "not_verified"


def test_full_verification_then_transfer_succeeds():
    ctx = FakeToolContext()

    q = tools.get_security_question("user_001", ctx)
    assert q["status"] == "success"
    assert ctx.state["verification_status"] == sm.QUESTION_ISSUED

    v = tools.validate_security_answer("Toronto", ctx)  # case-insensitive match
    assert v["status"] == "success"
    assert v["verified"] is True
    assert ctx.state["verification_status"] == sm.VERIFIED

    t = tools.execute_transfer("user_001", "checking", "savings", 500, ctx)
    assert t["status"] == "success"
    assert t["new_checking_balance"] == 2000.00
    assert t["new_savings_balance"] == 10500.00


def test_wrong_answer_then_correct_answer_within_attempt_cap():
    ctx = FakeToolContext()
    tools.get_security_question("user_001", ctx)

    wrong = tools.validate_security_answer("Ottawa", ctx)
    assert wrong["status"] == "retry"
    assert ctx.state["verification_status"] == sm.QUESTION_ISSUED  # allowed to retry

    correct = tools.validate_security_answer("toronto", ctx)
    assert correct["verified"] is True


def test_max_attempts_exceeded_locks_session():
    ctx = FakeToolContext()
    tools.get_security_question("user_001", ctx)

    for _ in range(sm.MAX_ATTEMPTS):
        result = tools.validate_security_answer("wrong", ctx)

    assert result["status"] == "failed"
    assert ctx.state["verification_status"] == sm.FAILED

    # Even a correct answer can't resurrect a FAILED session's transfer path
    blocked = tools.execute_transfer("user_001", "checking", "savings", 50, ctx)
    assert blocked["status"] == "error"
    assert blocked["reason"] == "not_verified"


def test_verification_for_one_user_does_not_authorize_transfer_for_another():
    """Gate 1 is tied to the specific user_id that was challenged, not just
    'someone succeeded verification in this session.'"""
    ctx = FakeToolContext()
    tools.get_security_question("user_001", ctx)
    tools.validate_security_answer("toronto", ctx)
    assert sm.is_verified(ctx.state)

    # user_002 was never challenged in this session -- must be blocked even
    # though the session's verification_status is VERIFIED.
    result = tools.execute_transfer("user_002", "checking", "savings", 50, ctx)
    assert result["status"] == "error"
    assert result["reason"] == "not_verified"


def test_insufficient_funds_is_independent_of_verification():
    """Gate 2 (business logic) applies only after Gate 1 (identity) passes."""
    ctx = FakeToolContext()
    tools.get_security_question("user_001", ctx)
    tools.validate_security_answer("toronto", ctx)

    result = tools.execute_transfer("user_001", "checking", "savings", 999999, ctx)
    assert result["status"] == "error"
    assert result["reason"] == "insufficient_funds"


def test_question_cannot_be_reissued_after_failure():
    ctx = FakeToolContext()
    tools.get_security_question("user_001", ctx)
    for _ in range(sm.MAX_ATTEMPTS):
        tools.validate_security_answer("wrong", ctx)

    result = tools.get_security_question("user_001", ctx)
    assert result["status"] == "error"


def test_concurrent_transfers_do_not_lose_updates():
    """Two overlapping transfer requests for the same user must both apply.

    The old SELECT-then-compute-in-Python-then-UPDATE pattern could let two
    concurrent calls read the same starting balance and have one silently
    overwrite the other's result. This would have failed under that pattern;
    the atomic single-statement UPDATE in execute_transfer fixes it."""
    each_verified_ctx = []
    for _ in range(5):
        ctx = FakeToolContext()
        ctx.state.update(
            {"verification_status": sm.VERIFIED, "attempts": 0, "pending_user_id": "user_001"}
        )
        each_verified_ctx.append(ctx)

    def do_transfer(ctx):
        tools.execute_transfer("user_001", "checking", "savings", 100, ctx)

    threads = [threading.Thread(target=do_transfer, args=(ctx,)) for ctx in each_verified_ctx]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = tools.get_portfolio_balance("user_001", FakeToolContext())
    assert result["checking_balance"] == 2000.00  # 2500 - (5 * 100)
    assert result["savings_balance"] == 10500.00  # 10000 + (5 * 100)


def test_security_gate_before_tool_blocks_unverified_execute_transfer():
    """The centralized before_tool_callback guard, independent of
    execute_transfer's own in-function check."""
    ctx = FakeToolContext()
    result = tools.security_gate_before_tool(
        tool=SimpleNamespace(name="execute_transfer"),
        args={"user_id": "user_001", "from_account": "checking", "to_account": "savings", "amount": 100},
        tool_context=ctx,
    )
    assert result is not None
    assert result["status"] == "error"
    assert result["reason"] == "not_verified"


def test_security_gate_before_tool_ignores_non_sensitive_tools():
    ctx = FakeToolContext()
    result = tools.security_gate_before_tool(
        tool=SimpleNamespace(name="get_portfolio_balance"),
        args={"user_id": "user_001"},
        tool_context=ctx,
    )
    assert result is None
