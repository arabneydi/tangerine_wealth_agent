"""
Root agent definition for the digital wealth management assistant.

Single agent, no multi-agent orchestration -- the assignment asks for
a state-aware security flow around one assistant, not a hierarchy of
specialized agents, so a single Agent with well-defined tools and
session state is the right amount of complexity here.
"""

from google.adk.agents import Agent

from .tools import (
    execute_transfer,
    get_portfolio_balance,
    get_security_question,
    security_gate_before_tool,
    validate_security_answer,
)

MODEL = "gemini-flash-latest"  # Flash: free-tier eligible, plenty capable for tool-calling.
# Pinned versions (e.g. gemini-2.5-flash) get retired for new API keys over time;
# the "-latest" alias is maintained by Google to always point at a live model.
# See docs/AI_USAGE.md for why this isn't pinned, and for the free-tier daily
# quota gotchas hit repeatedly during development (a handful of fallback
# models were used temporarily when this one's quota was exhausted).

INSTRUCTION = """
You are a digital wealth management assistant for a brokerage platform.

You handle two kinds of requests:
1. General queries (e.g. "what's my balance?") -- call get_portfolio_balance directly.
   These never require identity verification.
2. Sensitive actions (e.g. "transfer $500 from checking to savings") -- these
   REQUIRE identity verification before you may call execute_transfer.

STRICT VERIFICATION RULES -- follow these exactly, they are not suggestions:
- Before calling execute_transfer, you must confirm the session's verification
  state is VERIFIED. You cannot judge this yourself from conversation history --
  the only way to check or advance verification is by calling the tools.
- If the user requests a transfer and verification has not yet succeeded, your
  ONLY valid action is to call get_security_question and then ask the user that
  question. Do NOT attempt execute_transfer first "to see what happens."
- When the user answers the security question, call validate_security_answer
  with their exact answer. Do NOT decide yourself whether the answer is "close
  enough" -- the tool performs the real check.
- If validate_security_answer returns verified=false with status "retry", ask
  the user to try again. If it returns status "failed", tell the user
  verification has failed for this session and the transfer cannot proceed;
  do not keep retrying.
- Only after validate_security_answer returns verified=true may you call
  execute_transfer.

Always relay tool errors (insufficient funds, invalid account, etc.) to the
user in plain language rather than retrying automatically.
"""

root_agent = Agent(
    name="wealth_management_assistant",
    model=MODEL,
    instruction=INSTRUCTION,
    tools=[
        get_portfolio_balance,
        get_security_question,
        validate_security_answer,
        execute_transfer,
    ],
    # Defense-in-depth: intercepts sensitive tool calls before they run, as a
    # second, independent check alongside execute_transfer's own gate.
    before_tool_callback=security_gate_before_tool,
)
