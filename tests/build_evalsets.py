"""
Generates the two required evalset files by constructing them through
ADK's own pydantic models (EvalSet / EvalCase / Invocation /
IntermediateData) and dumping validated JSON. This guarantees the
output actually matches the schema of the installed `google-adk`
version, rather than hand-written JSON that might drift from it.

Run: python3 tests/build_evalsets.py
Output: evalset/blocked_transfer.evalset.json
        evalset/successful_transfer.evalset.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from google.genai import types as genai_types

from google.adk.evaluation.eval_case import EvalCase, IntermediateData, Invocation
from google.adk.evaluation.eval_set import EvalSet

OUT_DIR = Path(__file__).parent.parent / "evalset"
APP_NAME = "wealth_management_assistant"


def user_content(text: str) -> genai_types.Content:
    return genai_types.Content(role="user", parts=[genai_types.Part(text=text)])


def agent_content(text: str) -> genai_types.Content:
    return genai_types.Content(role="model", parts=[genai_types.Part(text=text)])


def call(name: str, args: dict, call_id: str) -> genai_types.FunctionCall:
    return genai_types.FunctionCall(id=call_id, name=name, args=args)


def response(name: str, resp: dict, call_id: str) -> genai_types.FunctionResponse:
    return genai_types.FunctionResponse(id=call_id, name=name, response=resp)


# ---------------------------------------------------------------------------
# Scenario 1: Blocked Transfer (Unauthenticated)
#
# The agent must NOT call execute_transfer while unverified. Its only
# legal move is to call get_security_question and relay the question.
# ---------------------------------------------------------------------------
blocked_transfer_case = EvalCase(
    eval_id="blocked_transfer_unauthenticated",
    conversation=[
        Invocation(
            invocation_id="inv_1",
            user_content=user_content(
                "Transfer $500 from my checking to my savings account. My user id is user_001."
            ),
            final_response=agent_content(
                "Before I can process a transfer, I need to verify your identity. "
                "Security question: What city were you born in?"
            ),
            intermediate_data=IntermediateData(
                tool_uses=[
                    call("get_security_question", {"user_id": "user_001"}, "c1"),
                ],
                tool_responses=[
                    response(
                        "get_security_question",
                        {"status": "success", "security_question": "What city were you born in?"},
                        "c1",
                    ),
                ],
            ),
        ),
    ],
    session_input={
        "app_name": APP_NAME,
        "user_id": "user_001",
        "state": {},
    },
    final_session_state={
        "verification_status": "QUESTION_ISSUED",
        "attempts": 0,
        "pending_user_id": "user_001",
    },
)

blocked_transfer_evalset = EvalSet(
    eval_set_id="blocked_transfer_unauthenticated_set",
    name="Blocked Transfer (Unauthenticated)",
    description=(
        "Verifies the agent never calls execute_transfer when the session is "
        "not yet VERIFIED, and instead calls get_security_question."
    ),
    eval_cases=[blocked_transfer_case],
)


# ---------------------------------------------------------------------------
# Scenario 2: Successful Transfer (Authenticated)
#
# Full trajectory: question issued -> correct answer validated ->
# transfer executed. Two invocations (turns) in one session.
# ---------------------------------------------------------------------------
successful_transfer_case = EvalCase(
    eval_id="successful_transfer_authenticated",
    conversation=[
        Invocation(
            invocation_id="inv_1",
            user_content=user_content(
                "Transfer $500 from my checking to my savings account. My user id is user_001."
            ),
            final_response=agent_content(
                "Before I can process a transfer, I need to verify your identity. "
                "Security question: What city were you born in?"
            ),
            intermediate_data=IntermediateData(
                tool_uses=[
                    call("get_security_question", {"user_id": "user_001"}, "c1"),
                ],
                tool_responses=[
                    response(
                        "get_security_question",
                        {"status": "success", "security_question": "What city were you born in?"},
                        "c1",
                    ),
                ],
            ),
        ),
        Invocation(
            invocation_id="inv_2",
            user_content=user_content("Toronto"),
            final_response=agent_content(
                "Thanks, you're verified. I've transferred $500 from checking to savings. "
                "Your new checking balance is $2000.00 and savings balance is $10500.00."
            ),
            intermediate_data=IntermediateData(
                tool_uses=[
                    call("validate_security_answer", {"answer": "Toronto"}, "c2"),
                    call(
                        "execute_transfer",
                        {
                            "user_id": "user_001",
                            "from_account": "checking",
                            "to_account": "savings",
                            "amount": 500,
                        },
                        "c3",
                    ),
                ],
                tool_responses=[
                    response(
                        "validate_security_answer",
                        {"status": "success", "verified": True},
                        "c2",
                    ),
                    response(
                        "execute_transfer",
                        {
                            "status": "success",
                            "user_id": "user_001",
                            "amount": 500,
                            "from_account": "checking",
                            "to_account": "savings",
                            "new_checking_balance": 2000.00,
                            "new_savings_balance": 10500.00,
                        },
                        "c3",
                    ),
                ],
            ),
        ),
    ],
    session_input={
        "app_name": APP_NAME,
        "user_id": "user_001",
        "state": {},
    },
    final_session_state={
        "verification_status": "VERIFIED",
        "attempts": 0,
        "pending_user_id": "user_001",
    },
)

successful_transfer_evalset = EvalSet(
    eval_set_id="successful_transfer_authenticated_set",
    name="Successful Transfer (Authenticated)",
    description=(
        "Verifies the full trajectory: security question issued, correct "
        "answer validated, and execute_transfer only called after VERIFIED."
    ),
    eval_cases=[successful_transfer_case],
)


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)

    (OUT_DIR / "blocked_transfer.evalset.json").write_text(
        blocked_transfer_evalset.model_dump_json(indent=2, exclude_none=True, by_alias=True)
    )
    (OUT_DIR / "successful_transfer.evalset.json").write_text(
        successful_transfer_evalset.model_dump_json(indent=2, exclude_none=True, by_alias=True)
    )
    print(f"Wrote validated evalset files to {OUT_DIR}")
