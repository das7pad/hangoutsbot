FROM python:3.5
LABEL description="Google Hangouts Bot"
LABEL maintainer="http://github.com/hangoutsbot/hangoutsbot"
WORKDIR /app
ADD requirements.txt .
RUN pip install -r requirements.txt
RUN mkdir /data
COPY hangupsbot/ ./
VOLUME /data
RUN mkdir -p /root/.local/share && ln -s /data /root/.local/share/hangupsbot
ADD docker-entrypoint.sh .
ENTRYPOINT ["./docker-entrypoint.sh"]
ARG PORTS="9001 9002 9003"
EXPOSE $PORTS
