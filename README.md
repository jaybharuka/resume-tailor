# resume-tailor

AI resume tailoring platform. Phase 1 delivers the architecture skeleton only —
see `docs/superpowers/specs/2026-07-03-phase1-architecture-design.md` for the
full design and `docs/superpowers/plans/2026-07-03-phase1-architecture.md` for
what was built.

## Local development

1. Copy `infra/.env.example` to `infra/.env` and fill in `GEMINI_API_KEY`
   (and `NVIDIA_API_KEY` once you have one).
2. This repo expects the existing `hiring-agent` repo checked out as a sibling
   directory (`../hiring-agent-imp` relative to this repo's parent). If your
   checkout doesn't match that layout (e.g. you're working inside a git
   worktree nested under this repo), set `HIRING_AGENT_IMP_PATH` in
   `infra/.env` to the correct path before running `docker compose up`.
3. From `infra/`: `docker compose up -d --build`
4. Check `curl http://localhost:8020/health`

## Running backend tests without Docker

    cd backend
    pip install -r requirements.txt -r requirements-dev.txt
    pytest

## Document generation (Phase 7) — Tectonic setup

Document generation compiles LaTeX to PDF using
[Tectonic](https://tectonic-typesetting.github.io/). To run the document
generation tests/smoke script locally (outside Docker), install Tectonic and
make sure it's on your `PATH`:

    # macOS (Homebrew)
    brew install tectonic

    # Linux/Windows: download a release binary from
    # https://github.com/tectonic-typesetting/tectonic/releases
    # or install via cargo: cargo install tectonic

**Package cache tradeoff (deliberate, not a bug):** Tectonic fetches needed
LaTeX packages from a bundle on first use and caches them locally
(`~/.cache/Tectonic` by default) for every compile after that. The Docker
image pre-warms this cache at build time, so the deployed container never
needs network access to compile a resume. Local dev does **not** pre-warm —
the first time you run the document-generation tests or smoke script after
installing Tectonic, that first compile will need network access to
populate your local cache; every compile after that is offline and fast.
If your `pytest` run doesn't have network access the very first time, the
Tectonic-dependent test will report a real failure (not a skip) rather than
silently passing — that's expected on a first run without connectivity, and
resolves itself on any subsequent run once the cache is populated.
