# How AI Was Used

I used Claude (Anthropic) as a design and implementation collaborator
throughout this assignment — from scoping the design, to writing and testing
the code, to a final adversarial pass before submission. This wasn't
one-shot generation: I went through the high-level design step by step
before any code was written, correcting specific choices along the way
(what state actually needed to be tracked, which test cases mattered), and
later read the entire codebase and test suite line by line — asking why
each specific format, function, or design choice was made, until I could
account for every part myself (how `tool_context`, `state`, and `session`
relate; why SQLite over Parquet; where retry logic and error handling
actually live) rather than just trusting that it worked. A few concrete
examples of where pushing back on its first answer led to a real change:

- **Don't trust a green test result — verify it.** Once the implementation
  looked done, I had Claude critically re-review the whole project against
  the assignment PDF instead of taking its own word for it. That's what
  caught a model that had quietly been deprecated by Google mid-project: the
  evals reported "passing" while every real API call was actually failing —
  a genuine blind spot in ADK's own eval tooling. Fixing it meant switching
  models and re-verifying against live calls, not just re-reading test output.
- **Asked harder engineering questions than the assignment required.**
  Concurrency safety, idempotency under a crash, whether tool calls are
  authorized before or only inside execution — none explicitly asked for by
  the PDF. That pressure surfaced two real bugs: a race condition in the
  transfer logic that could silently drop a concurrent transfer, and a
  security check that lived only inside one function instead of being
  independently guarded. Both got fixed and covered by new tests.
- **Unit testing caught a real security gap early on**: an early version of
  the transfer tool checked "is the session verified" but not "verified *for
  this specific user*" — a test written to probe exactly that failed,
  exposing that a verified session could move funds for a different user
  than the one actually challenged. Fixed before it ever became a demo bug.


## A feedback on the assignment 

`AgentEvaluator.evaluate()` reports success when every invocation in an eval
case errors out (e.g. from a missing key or a dead model), rather than
failing — worth reporting upstream, since it can give any candidate false
confidence that their evalset is passing when it's never really being
exercised at all.