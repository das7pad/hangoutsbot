FROM python:3.5
LABEL description="Google Hangouts Bot"
LABEL maintainer="http://github.com/das7pad/hangoutsbot"
WORKDIR /app
RUN mkdir /data
VOLUME /data
RUN mkdir -p /root/.local/share && ln -s /data /root/.local/share/hangupsbot
ENTRYPOINT ["./docker-entrypoint.sh"]
ARG PORTS="9001 9002 9003"
EXPOSE $PORTS
COPY docker-entrypoint.sh Makefile setup.py ./
COPY hangupsbot ./hangupsbot
RUN make install
