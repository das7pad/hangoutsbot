# pylint: skip-file
__all__ = (
    'AsyncRequestHandler',
    'SimpleAsyncRequestHandler',
)


import base64
import imghdr
import io
import json
import logging
import time
from urllib.parse import parse_qs

from aiohttp import web

from hangupsbot.base_models import BotMixin


logger = logging.getLogger(__name__)


class AsyncRequestHandler(BotMixin):
    _bot = None  # ensure backward compatibility for legacy subclasses

    def __init__(self, *args):
        # pylint:disable=unused-argument
        self.sinkname = self.__class__.__name__
        self._bot = self.bot  # backward-compatibility

    def addroutes(self, router):
        router.add_route("POST", "/{convid}", self.adapter_do_post)
        router.add_route("POST", "/{convid}/", self.adapter_do_post)

    async def adapter_do_post(self, request):
        raw_content = await request.content.read()

        results = await self.process_request(request.path,
                                             parse_qs(request.query_string),
                                             raw_content.decode("utf-8"))

        if results:
            content_type = "text/html"
            results = results.encode("ascii", "xmlcharrefreplace")
        else:
            content_type = "text/plain"
            results = "OK".encode('utf-8')

        return web.Response(body=results, content_type=content_type)

    async def process_request(self, path, query_string, content):
        payload = json.loads(content)

        path = path.split("/")
        conversation_id = path[1]
        if not conversation_id:
            raise ValueError("conversation id must be provided in path")

        text = None
        if "echo" in payload:
            text = payload["echo"]

        image_raw = None
        image_data = None
        image_filename = None
        if "image" in payload:
            if "base64encoded" in payload["image"]:
                image_raw = base64.b64decode(payload["image"]["base64encoded"])
                image_data = io.BytesIO(image_raw)

            if "filename" in payload["image"]:
                image_filename = payload["image"]["filename"]
            else:
                image_type = imghdr.what('ignore', image_raw)
                image_filename = str(int(time.time())) + "." + image_type
                logger.info(
                    "automatic image filename: {}".format(image_filename))

        if not text and not image_data:
            raise ValueError("nothing to send")

        results = await self.send_data(conversation_id, text,
                                       image_data=image_data,
                                       image_filename=image_filename)

        return results

    async def send_data(self, conversation_id, text, image_data=None,
                        image_filename=None, context=None):
        """sends text and/or image to a conversation
        image_filename is recommended but optional, fallbacks to
        <timestamp>.jpg if undefined
        process_request() should determine the image extension prior to this
        """
        image_id = None
        if image_data:
            if not image_filename:
                image_filename = str(int(time.time())) + ".jpg"
                logger.info(
                    "fallback image filename: {}".format(image_filename))

            image_id = await self.bot.upload_image(image_data,
                                                   filename=image_filename)

        if not text and not image_id:
            raise ValueError("nothing to send")

        await self.bot.coro_send_message(conversation_id, text, context=context,
                                         image_id=image_id)
        return "OK"


class SimpleAsyncRequestHandler(AsyncRequestHandler):
    logger = logger

    async def process_request(self, path, query_string, content):
        conversation_id = path.split("/")[1]
        if not conversation_id:
            self.logger.warning("invalid path %r", path)
            return

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as err:
            self.logger.warning("invalid payload %r", err)
            return

        await self.process_payload(conversation_id, payload)

    async def process_payload(self, conv_or_user_id, payload):
        """Process a message

        Args:
            conv_or_user_id (str): a conversation id or a user id
            payload (dict): the json payload
        """
