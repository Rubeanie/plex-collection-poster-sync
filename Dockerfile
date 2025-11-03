FROM python:3.14-slim

# Build arguments for user/group IDs (default: 1000:1000)
ARG USER_ID=1000
ARG GROUP_ID=1000
ARG SUPERCRONIC_VERSION=0.2.38

# Install system dependencies and supercronic
RUN apt-get -y update && \
    apt-get -y install wget ca-certificates bash && \
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        ARCH_SUFFIX="amd64"; \
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        ARCH_SUFFIX="arm64"; \
    elif [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armhf" ]; then \
        ARCH_SUFFIX="arm"; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    wget -O /usr/local/bin/supercronic https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH_SUFFIX} && \
    chmod +x /usr/local/bin/supercronic && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user with configurable UID/GID
RUN getent group ${GROUP_ID} >/dev/null || groupadd -r -g ${GROUP_ID} appuser && \
    getent passwd ${USER_ID} >/dev/null || useradd -r -u ${USER_ID} -g ${GROUP_ID} -d /app -s /bin/bash appuser

# Setup directory and copying files
WORKDIR /app
COPY ./start.sh ./start.sh
COPY ./collection_poster_sync.py ./collection_poster_sync.py
COPY ./requirements.txt ./requirements.txt
# Fix Windows line endings (CRLF -> LF) and make executable
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Create log directory with proper permissions (crontab created at runtime)
# Use numeric UID/GID for chown to avoid issues if username doesn't exist
RUN mkdir -p /app && \
    chown -R ${USER_ID}:${GROUP_ID} /app

# Switch to non-root user (use numeric UID for reliability)
USER ${USER_ID}:${GROUP_ID}

CMD ./start.sh
