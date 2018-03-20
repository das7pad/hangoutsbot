FROM python:3.6
LABEL description="Google Hangouts Bot"
LABEL maintainer="http://github.com/das7pad/hangoutsbot"
WORKDIR /app
RUN mkdir /data
VOLUME /data
RUN mkdir -p /root/.local/share && ln -s /data /root/.local/share/hangupsbot
ENTRYPOINT ["/app/venv/bin/hangupsbot"]
ARG PORTS="9001 9002 9003"
EXPOSE $PORTS
COPY Makefile setup.py requirements.txt ./
COPY hangupsbot ./hangupsbot
RUN make install
