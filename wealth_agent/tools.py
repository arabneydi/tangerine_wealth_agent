"""
ADK tool functions for the wealth management assistant.

Four tools total (2 required by the assignment + 2 needed to make the
verification flow actually work end-to-end):

    get_portfolio_balance    -- required, unguarded
    get_security_question    -- required, triggers the identity gate
    validate_security_answer -- gate completion; NOT judged by the LLM
    execute_transfer         -- the sensitive action; hard-gated on VERIFIED

Each function follows the ADK convention: a plain Python function with
type hints and a docstring (the docstring becomes the tool description
the LLM sees), plus an optional `tool_context: ToolContext` parameter
that ADK injects automatically. Session state lives on
`tool_context.state` and persists across turns within a session.

This module also defines `security_gate_before_tool`, which is NOT a tool
itself -- it's registered separately in agent.py as ADK's
`before_tool_callback`, a defense-in-depth guard that runs before any of
the four tools above execute. See its own docstring below.
"""

from google.adk.tools import ToolContext

from . import state_machine as sm
from .database import get_connection


def _normalize(answer: str) -> str:
    return answer.strip().lower()


def get_portfolio_balance(user_id: str, tool_context: ToolContext) -> dict:
    """Retrieve the checking and savings balances for a given user.

    This is a general, non-sensitive query and is never gated by
    identity verification -- it does not touch verification state.

    Args:
        user_id: The account holder's user id.

    Returns:
        dict with checking_balance and savings_balance, or an error
        if the user_id is not found.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT checking_balance, savings_balance FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return {"status": "error", "message": f"No account found for user_id '{user_id}'."}

    return {
        "status": "success",
        "user_id": user_id,
        "checking_balance": row["checking_balance"],
        "savings_balance": row["savings_balance"],
    }


def get_security_question(user_id: str, tool_context: ToolContext) -> dict:
    """Issue the security question for a user, starting or continuing identity verification.

    This is the only legal move when a sensitive action (e.g. transfer)
    is requested and the session is not yet VERIFIED. Calling this
    transitions verification state to QUESTION_ISSUED.

    Args:
        user_id: The account holder's user id.

    Returns:
        dict with the security question text, or an error if the
        user_id is not found or the verification attempt cap was
        already reached this session.
    """
    state = tool_context.state
    if "verification_status" not in state:
        state.update(sm.new_state())

    if state.get("verification_status") == sm.FAILED:
        return {
            "status": "error",
            "message": "Verification previously failed for this session. Cannot re-issue a question.",
        }

    with get_connection() as conn:
        row = conn.execute(
            "SELECT security_question FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

    if row is None:
        return {"status": "error", "message": f"No user found for user_id '{user_id}'."}

    sm.issue_question(state, user_id)

    return {"status": "success", "security_question": row["security_question"]}


def validate_security_answer(answer: str, tool_context: ToolContext) -> dict:
    """Validate the user's answer to the previously issued security question.

    The comparison is a deterministic, normalized string match done in
    code -- never left to the LLM's judgment -- since letting the model
    decide "close enough" on a security check is a real vulnerability.

    Args:
        answer: The user's answer to the security question.

    Returns:
        dict indicating whether verification succeeded, failed, or was
        attempted out of order (no question was issued this session).
    """
    state = tool_context.state
    if state.get("verification_status") != sm.QUESTION_ISSUED:
        return {
            "status": "error",
            "message": "No security question is currently pending for this session.",
        }

    user_id = state.get("pending_user_id")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT security_answer FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

    correct = row is not None and _normalize(answer) == _normalize(row["security_answer"])
    sm.record_answer_result(state, correct)

    if correct:
        return {"status": "success", "verified": True}

    remaining = sm.MAX_ATTEMPTS - state["attempts"]
    if state["verification_status"] == sm.FAILED:
        return {"status": "failed", "verified": False, "message": "Maximum attempts exceeded."}
    return {
        "status": "retry",
        "verified": False,
        "message": f"Incorrect answer. {remaining} attempt(s) remaining.",
    }


def execute_transfer(
    user_id: str, from_account: str, to_account: str, amount: float, tool_context: ToolContext
) -> dict:
    """Transfer funds between a user's checking and savings accounts.

    Hard-gated on identity verification: this tool refuses to run
    unless verification_status == VERIFIED for this session. This
    check happens in code, not as an instruction the LLM might forget
    or be talked out of.

    Once past the identity gate, ordinary business-logic validation
    applies (valid account names, sufficient funds, positive amount) --
    these are independent of, and unrelated to, identity verification.

    Args:
        user_id: The account holder's user id.
        from_account: Either "checking" or "savings".
        to_account: Either "checking" or "savings".
        amount: Amount to transfer; must be positive.

    Returns:
        dict indicating success or the specific reason for failure.
    """
    state = tool_context.state

    # --- Gate 1: identity verification (state machine) ---
    # Verified must apply to THIS user_id, not merely "someone" in this
    # session -- otherwise a verified session could be reused to move
    # funds for a different user_id than the one who was challenged.
    if not sm.is_verified(state) or state.get("pending_user_id") != user_id:
        return {
            "status": "error",
            "reason": "not_verified",
            "message": "Identity verification is required before a transfer can be executed.",
        }

    # --- Gate 2: business logic (independent of identity) ---
    valid_accounts = {"checking", "savings"}
    if from_account not in valid_accounts or to_account not in valid_accounts:
        return {"status": "error", "reason": "invalid_account", "message": "Account must be 'checking' or 'savings'."}
    if from_account == to_account:
        return {"status": "error", "reason": "invalid_account", "message": "Source and destination accounts must differ."}
    if amount <= 0:
        return {"status": "error", "reason": "invalid_amount", "message": "Transfer amount must be positive."}

    # The debit/credit and the sufficient-funds check happen in a single
    # atomic UPDATE, not a SELECT-then-compute-in-Python-then-UPDATE -- the
    # latter is a read-modify-write race under concurrent transfers for the
    # same user_id (two overlapping requests can both read the same starting
    # balance and one silently overwrites the other's result). from_account
    # and to_account are already validated against {"checking", "savings"}
    # above, so interpolating them into the column name is safe.
    from_col = f"{from_account}_balance"
    to_col = f"{to_account}_balance"

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE accounts SET {from_col} = {from_col} - ?, {to_col} = {to_col} + ? "
            f"WHERE user_id = ? AND {from_col} >= ?",
            (amount, amount, user_id, amount),
        )
        conn.commit()

        if cursor.rowcount == 0:
            row = conn.execute(
                "SELECT checking_balance, savings_balance FROM accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return {"status": "error", "reason": "invalid_account", "message": f"No account found for user_id '{user_id}'."}
            return {
                "status": "error",
                "reason": "insufficient_funds",
                "message": f"Insufficient funds in {from_account} (balance: {row[from_col]}).",
            }

        row = conn.execute(
            "SELECT checking_balance, savings_balance FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return {
        "status": "success",
        "user_id": user_id,
        "amount": amount,
        "from_account": from_account,
        "to_account": to_account,
        "new_checking_balance": row["checking_balance"],
        "new_savings_balance": row["savings_balance"],
    }


# Tools that must never run unless the session is VERIFIED for the target
# user_id. execute_transfer already enforces this itself (Gate 1, above) --
# this set drives a *second*, independent enforcement point (see
# security_gate_before_tool below), so a future sensitive tool that forgets
# its own in-function check is still caught centrally rather than silently
# unguarded.
SENSITIVE_TOOLS = {"execute_transfer"}


def security_gate_before_tool(tool, args: dict, tool_context: ToolContext) -> dict | None:
    """ADK `before_tool_callback`: runs before any tool call executes.

    Registered on the agent (see agent.py), not called directly by this
    module. Returning a dict here short-circuits the call entirely -- the
    real tool function never runs -- so this is enforcement *before* the
    tool, not just inside it. Returning None lets the tool proceed normally.

    This is deliberately redundant with execute_transfer's own Gate 1: two
    independent checks that must both agree, rather than one that could be
    forgotten if this list of tools ever grows.
    """
    if tool.name not in SENSITIVE_TOOLS:
        return None

    state = tool_context.state
    user_id = args.get("user_id")
    if not sm.is_verified(state) or state.get("pending_user_id") != user_id:
        return {
            "status": "error",
            "reason": "not_verified",
            "message": "Identity verification is required before this action can be executed.",
        }
    return None
