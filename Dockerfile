FROM python:3.6
LABEL description="Google Hangouts Bot" \
      maintainer="https://github.com/das7pad/hangoutsbot"

RUN adduser --system --uid 10000 --group --home /data hangupsbot

VOLUME /data
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/hangupsbot", "--base_dir", "/data"]

ARG TZ="Europe/Berlin"
ARG PORTS="9001 9002 9003"
EXPOSE $PORTS

COPY . /app
RUN \
    pip3 install /app --process-dependency-links --no-cache-dir && rm -rf /app; \
    python3 -c "import imageio; imageio.plugins.ffmpeg.download()" && \
        cd /usr/local/lib/python3*/site-packages/imageio/resources/ && \
        mv /root/.imageio/ffmpeg ./ && chown -R hangupsbot ffmpeg/; \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone; \
    true

USER hangupsbot
