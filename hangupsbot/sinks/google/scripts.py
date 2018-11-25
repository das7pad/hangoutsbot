import logging

from hangupsbot.sinks.base_bot_request_handler import SimpleAsyncRequestHandler


logger = logging.getLogger(__name__)


class GoogleWebHookReceiver(SimpleAsyncRequestHandler):
    logger = logger

    async def process_payload(self, conv_or_user_id, payload):
        if not payload:
            logger.error("payload has nothing")
            return

        if "message" not in payload:
            logger.info('payload %s: %r', id(payload), payload)
            logger.error("payload %s: does not contain message", id(payload))
            return

        await self.send_actionable_message(conv_or_user_id, payload["message"])

    async def send_actionable_message(self, target, content):
        if target in self.bot.conversations:
            await self.bot.coro_send_message(target, content)
        else:
            # attempt to send to a user id
            await self.bot.coro_send_to_user(target, content)
