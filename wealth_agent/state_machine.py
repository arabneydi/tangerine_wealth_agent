"""
Identity-verification state machine.

This is deliberately isolated from ADK and from the LLM: it is the
"security gate" described in the design doc, and it is plain,
deterministic Python so it can be unit-tested on its own and so the
agent can never talk its way around it.

States:
    UNVERIFIED      -- default; no sensitive action may proceed
    QUESTION_ISSUED -- a security question has been given to the user
    VERIFIED        -- answer validated; sensitive actions may proceed
    FAILED          -- max attempts exhausted; sensitive actions blocked

This state machine answers exactly one question: "has this session
proven the user's identity." It says nothing about whether a
subsequent transfer is otherwise valid (funds, account names, etc) --
that is a separate, ordinary business-logic check performed after the
gate, not part of this state machine.
"""

UNVERIFIED = "UNVERIFIED"
QUESTION_ISSUED = "QUESTION_ISSUED"
VERIFIED = "VERIFIED"
FAILED = "FAILED"

MAX_ATTEMPTS = 3

VALID_TRANSITIONS = {
    UNVERIFIED: {QUESTION_ISSUED},
    QUESTION_ISSUED: {VERIFIED, FAILED, QUESTION_ISSUED},  # re-issue on wrong answer, within attempt cap
    VERIFIED: set(),   # terminal (success) for this session's verification purposes
    FAILED: set(),     # terminal (failure); a new session/turn must restart verification
}


class InvalidTransitionError(Exception):
    """Raised when a state transition outside the allowed graph is attempted.

    In production this should be treated as a data-integrity bug (see the
    observability doc, Section 2: "state inconsistencies") and logged
    accordingly, not swallowed.
    """


def new_state() -> dict:
    """Return a fresh verification-state dict, e.g. to seed ADK session state."""
    return {
        "verification_status": UNVERIFIED,
        "attempts": 0,
        "pending_user_id": None,
    }


def issue_question(state: dict, user_id: str) -> dict:
    """Transition UNVERIFIED (or QUESTION_ISSUED) -> QUESTION_ISSUED."""
    current = state.get("verification_status", UNVERIFIED)
    if QUESTION_ISSUED not in VALID_TRANSITIONS.get(current, set()) and current != QUESTION_ISSUED:
        raise InvalidTransitionError(f"Cannot issue question from state {current}")
    state["verification_status"] = QUESTION_ISSUED
    state["pending_user_id"] = user_id
    return state


def record_answer_result(state: dict, correct: bool) -> dict:
    """Transition QUESTION_ISSUED -> VERIFIED or FAILED/QUESTION_ISSUED, enforcing the attempt cap."""
    current = state.get("verification_status", UNVERIFIED)
    if current != QUESTION_ISSUED:
        raise InvalidTransitionError(
            f"Cannot record an answer from state {current}; a question must be issued first"
        )

    if correct:
        state["verification_status"] = VERIFIED
        return state

    state["attempts"] = state.get("attempts", 0) + 1
    if state["attempts"] >= MAX_ATTEMPTS:
        state["verification_status"] = FAILED
    else:
        state["verification_status"] = QUESTION_ISSUED  # allow a retry, within the cap
    return state


def is_verified(state: dict) -> bool:
    return state.get("verification_status") == VERIFIED
