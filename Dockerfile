# syntax=docker/dockerfile:1
# ponytail: multi-stage, non-root, pinned by digest. /app/sloane layout so both
# `import shared` (cwd on sys.path) and `python -m sloane.*` (PYTHONPATH=/app) resolve.
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS build
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS runtime
RUN useradd -r -u 1001 -g nogroup -d /app -s /sbin/nologin sloane
WORKDIR /app/sloane
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY . /app/sloane
USER sloane
CMD ["python", "-m", "sloane.ingest_loop"]
