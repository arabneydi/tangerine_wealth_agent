"""
Loads wealth_agent/.env (GOOGLE_API_KEY) before tests run, so
`pytest tests/test_evalsets.py` works the same way `adk web` / `adk eval`
already do (both auto-load that file via ADK's own dotenv convention).
Explicit env vars set in the shell still take precedence.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "wealth_agent" / ".env")