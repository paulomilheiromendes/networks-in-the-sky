# Python simulation image (Docker track). Build from the repository root:
#   docker build -t sky-py:1.0 -f docker/py.Dockerfile .       (or: make images)
#
# Only the packages are baked in. Your code in sim/ is mounted read-only at
# /code when the notebook runs a job, so editing it needs no rebuild.
# Rebuild only when docker/requirements-sim.txt changes (and bump the tag).
FROM python:3.11-slim-bookworm

COPY docker/requirements-sim.txt /tmp/requirements-sim.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sim.txt

WORKDIR /code
