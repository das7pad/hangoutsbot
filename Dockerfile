FROM python:3.6
LABEL description="Google Hangouts Bot"
LABEL maintainer="http://github.com/das7pad/hangoutsbot"

RUN adduser --system --uid 10000 --group --home /data hangupsbot

VOLUME /data
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/hangupsbot", "--base_dir", "/data"]

ARG PORTS="9001 9002 9003"
EXPOSE $PORTS

COPY . /app
RUN pip3 install /app --process-dependency-links

USER hangupsbot
