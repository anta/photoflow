FROM python:3.12-slim AS builder

WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.lock ./
RUN /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PHOTOFLOW_NAS_ROOT=/photos \
    PHOTOFLOW_DATA_DIR=/data \
    PHOTOFLOW_HOST=0.0.0.0 \
    PHOTOFLOW_PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 photoflow \
    && useradd --uid 10001 --gid photoflow --no-create-home --shell /usr/sbin/nologin photoflow \
    && install -d -o photoflow -g photoflow -m 0700 /data

COPY --from=builder /opt/venv /opt/venv
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/photoflow-entrypoint
WORKDIR /app
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["photoflow-entrypoint"]
CMD ["serve"]
