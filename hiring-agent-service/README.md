# hiring-agent-service

Thin HTTP wrapper around the existing `hiring-agent` repo. Never modifies that
repo — only imports from it.

## Running locally

Requires the `hiring-agent` repo checked out as a sibling directory (default:
`../hiring-agent-imp` relative to this service), or set `HIRING_AGENT_REPO_PATH`
to point elsewhere. Also requires `GEMINI_API_KEY` in the environment for real
evaluations (not needed to run the test suite, which mocks `ResumeEvaluator`).

    pip install -r requirements.txt -r requirements-dev.txt
    pytest
    uvicorn app:app --host 0.0.0.0 --port 8100
