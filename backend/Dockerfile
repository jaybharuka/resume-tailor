FROM python:3.11-slim

WORKDIR /app

# Pinned to the exact release verified working in this phase's live Docker
# check (rather than piping the installer script, which resolves whatever
# version it currently bakes in) - an unpinned version is exactly what let
# the libgraphite2 shared-library failure above go unnoticed until a real
# build was attempted.
ARG TECTONIC_VERSION=0.16.9
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgraphite2-3 \
    && curl --proto '=https' --tlsv1.2 -fsSL -o tectonic.tar.gz \
        "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-gnu.tar.gz" \
    && tar xzf tectonic.tar.gz \
    && rm tectonic.tar.gz \
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
