# syntax=docker/dockerfile:1.6
FROM python:3.14-slim

# Build arguments for user/group IDs (default: 1000:1000)
ARG USER_ID=1000
ARG GROUP_ID=1000
ARG SUPERCRONIC_VERSION=0.2.38
# TARGETARCH is automatically set by Docker Buildx for multi-architecture builds
ARG TARGETARCH

# Install system dependencies and supercronic
RUN apt-get -y update && \
    apt-get -y install --no-install-recommends wget ca-certificates bash && \
    if [ "$TARGETARCH" = "amd64" ]; then \
        ARCH_SUFFIX="amd64"; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        ARCH_SUFFIX="arm64"; \
    elif [ "$TARGETARCH" = "arm" ]; then \
        ARCH_SUFFIX="arm"; \
    else \
        echo "Unsupported architecture: $TARGETARCH" >&2 && exit 1; \
    fi && \
    wget --tries=1 --timeout=10 --quiet -O /usr/local/bin/supercronic https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH_SUFFIX} && \
    test -s /usr/local/bin/supercronic || (echo "Failed to download supercronic binary or file is empty" >&2 && exit 1) && \
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
    pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    pip cache purge

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

# Set environment variable to prevent Python bytecode generation
ENV PYTHONDONTWRITEBYTECODE=1

CMD ./start.sh
