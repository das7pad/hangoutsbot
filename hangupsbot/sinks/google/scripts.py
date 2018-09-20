import json
import logging

from hangupsbot.sinks.base_bot_request_handler import AsyncRequestHandler


logger = logging.getLogger(__name__)


class WebhookReceiver(AsyncRequestHandler):

    async def process_request(self, path, query_string, content):
        path = path.split("/")
        conv_or_user_id = path[1]
        if conv_or_user_id is None:
            logger.error(
                "conversation or user id must be provided as part of path")
            return

        payload = content
        if isinstance(payload, str):
            payload = json.loads(payload)

        if not payload:
            logger.error("payload has nothing")
            return

        if "message" not in payload:
            logger.error("payload does not contain message")
            return

        await self.send_actionable_message(conv_or_user_id, payload["message"])

    async def send_actionable_message(self, target, content):
        if target in self.bot.conversations:
            await self.bot.coro_send_message(target, content)
        else:
            # attempt to send to a user id
            await self.bot.coro_send_to_user(target, content)
