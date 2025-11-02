FROM python:3.10

# Install system dependencies
RUN apt-get -y update && \
    apt-get -y install cron && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

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

# Create log file
RUN touch /var/log/cron.log

CMD ./start.sh
