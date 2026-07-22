# syntax=docker/dockerfile:1.6
FROM python:3.14-slim

# Build arguments for user/group IDs (default: 1000:1000)
ARG USER_ID=1000
ARG GROUP_ID=1000
ARG SUPERCRONIC_VERSION=0.2.38
# Per-arch SUPERCRONIC_SHA1 sums below are published in the GitHub release notes
# for this version — update them when bumping SUPERCRONIC_VERSION
# TARGETARCH is automatically set by Docker Buildx for multi-architecture builds
ARG TARGETARCH

# Install system dependencies and supercronic
RUN apt-get -y update && \
    apt-get -y install --no-install-recommends wget ca-certificates bash && \
    if [ "$TARGETARCH" = "amd64" ]; then \
        ARCH_SUFFIX="amd64"; SUPERCRONIC_SHA1="bc072eba2ae083849d5f86c6bd1f345f6ed902d0"; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        ARCH_SUFFIX="arm64"; SUPERCRONIC_SHA1="37842646e4c95b193c469afae400966565c383d3"; \
    elif [ "$TARGETARCH" = "arm" ]; then \
        ARCH_SUFFIX="arm"; SUPERCRONIC_SHA1="510b84b031b78ebe25b1f00c91ced3434edcd383"; \
    else \
        echo "Unsupported architecture: $TARGETARCH" >&2 && exit 1; \
    fi && \
    wget --tries=3 --timeout=10 --quiet -O /usr/local/bin/supercronic https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH_SUFFIX} && \
    test -s /usr/local/bin/supercronic || (echo "Failed to download supercronic binary or file is empty" >&2 && exit 1) && \
    echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - && \
    chmod +x /usr/local/bin/supercronic && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create non-root user with configurable UID/GID
RUN getent group ${GROUP_ID} >/dev/null || groupadd -r -g ${GROUP_ID} appuser && \
    getent passwd ${USER_ID} >/dev/null || useradd -r -u ${USER_ID} -g ${GROUP_ID} -d /app -s /bin/bash appuser

# Setup directory and copying files
WORKDIR /app
COPY ./requirements.txt ./requirements.txt

# Install Python packages (optimized for speed and caching with BuildKit cache mounts)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install -r /app/requirements.txt

# Copy application files
COPY ./start.sh ./start.sh
COPY ./collection_poster_sync.py ./collection_poster_sync.py
# Fix Windows line endings (CRLF -> LF) and make executable
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Create log directory with proper permissions (crontab created at runtime)
# Use numeric UID/GID for chown to avoid issues if username doesn't exist
RUN mkdir -p /app && \
    chown -R ${USER_ID}:${GROUP_ID} /app

# Switch to non-root user (use numeric UID for reliability)
USER ${USER_ID}:${GROUP_ID}

# No bytecode files; unbuffered stdout so log lines aren't lost on a crash
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Exec form so start.sh (and supercronic via exec) runs as PID 1 and receives signals directly
CMD ["./start.sh"]
