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

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
&&  mkdir /app \
&&  true

COPY requirements.txt /app
RUN pip3 install \
        --process-dependency-links \
        --no-cache-dir \
        -r /app/requirements.txt \
&&  python3 -c "import imageio; imageio.plugins.ffmpeg.download()" \
        && cd /usr/local/lib/python3*/site-packages/imageio/resources/ \
        && mv /root/.imageio/ffmpeg ./ \
        && chmod -R 555 ffmpeg/ \
&&  true

COPY . /app
RUN \
    pip3 install /app --process-dependency-links --no-cache-dir && rm -rf /app; \
    true

USER hangupsbot
