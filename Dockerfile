FROM python:3.6
LABEL description="Google Hangouts Bot"
LABEL maintainer="http://github.com/das7pad/hangoutsbot"
WORKDIR /app
RUN mkdir /data
VOLUME /data
ENTRYPOINT ["/app/venv/bin/hangupsbot", "--base_dir", "/data"]
ARG PORTS="9001 9002 9003"
EXPOSE $PORTS
COPY Makefile setup.py requirements.txt ./
COPY hangupsbot ./hangupsbot
RUN make install
