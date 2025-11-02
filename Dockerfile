FROM python:3.10

RUN apt-get -y update
RUN apt-get -y install cron

# Setup directory and copying files
WORKDIR /
RUN mkdir app
WORKDIR /app
COPY ./start.sh ./start.sh
COPY ./collection_poster_sync.py ./collection_poster_sync.py
COPY ./requirements.txt ./requirements.txt
RUN chmod +x start.sh

# Install Python packages.
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

RUN touch /var/log/cron.log

CMD ./start.sh
