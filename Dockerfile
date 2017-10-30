FROM python:3.5
LABEL description="Google Hangouts Bot"
LABEL maintainer="http://github.com/hangoutsbot/hangoutsbot"
WORKDIR /app
RUN mkdir /data
VOLUME /data
RUN mkdir -p /root/.local/share && ln -s /data /root/.local/share/hangupsbot
ENTRYPOINT ["./docker-entrypoint.sh"]
ARG PORTS="9001 9002 9003"
EXPOSE $PORTS
COPY docker-entrypoint.sh requirements.txt hangupsbot ./
RUN pip install -r requirements.txt
