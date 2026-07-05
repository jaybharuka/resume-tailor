FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgraphite2-3 \
    && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/tectonic \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-warm Tectonic's LaTeX package cache at build time with a throwaway
# compile, so the deployed container never needs network access to fetch
# packages when compiling a real resume at request time (see the Phase 7
# spec, section 4, for the full tradeoff rationale - local dev/fresh
# checkouts deliberately do NOT do this, and pay a one-time network cost on
# first local compile instead).
RUN mkdir -p /tmp/tectonic-warmup \
    && printf '\\documentclass{article}\n\\begin{document}\nwarmup\n\\end{document}\n' > /tmp/tectonic-warmup/warmup.tex \
    && tectonic /tmp/tectonic-warmup/warmup.tex --outdir /tmp/tectonic-warmup \
    && rm -rf /tmp/tectonic-warmup

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
