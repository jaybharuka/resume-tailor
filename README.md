# resume-tailor

AI resume tailoring platform. Phase 1 delivers the architecture skeleton only —
see `docs/superpowers/specs/2026-07-03-phase1-architecture-design.md` for the
full design and `docs/superpowers/plans/2026-07-03-phase1-architecture.md` for
what was built.

## Local development

1. Copy `infra/.env.example` to `infra/.env` and fill in `GEMINI_API_KEY`
   (and `NVIDIA_API_KEY` once you have one).
2. This repo expects the existing `hiring-agent` repo checked out as a sibling
   directory (`../hiring-agent-imp` relative to this repo's parent).
3. From `infra/`: `docker compose up -d --build`
4. Check `curl http://localhost:8020/health`

## Running backend tests without Docker

    cd backend
    pip install -r requirements.txt -r requirements-dev.txt
    pytest
