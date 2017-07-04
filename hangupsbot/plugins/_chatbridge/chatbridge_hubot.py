# pylint: skip-file
import aiohttp
import asyncio
import json
import logging

from webbridge import WebFramework, IncomingRequestHandler


logger = logging.getLogger(__name__)


class BridgeInstance(WebFramework):
    def _send_to_external_chat(self, bot, event, config):
        """override WebFramework._send_to_external_chat()"""
        async def _send():
            async with aiohttp.ClientSession() as session:
                await session.post(url, data=json.dumps(payload),
                                   headers=headers, connector=connector)
        if event.from_bot:
            # don't send my own messages
            return

        conversation_id = event.conv_id
        conversation_text = event.text

        user_id = event.user_id

        url = config["HUBOT_URL"] + conversation_id
        payload = {"from" : str(user_id.chat_id), "message" : conversation_text}
        headers = {'content-type': 'application/json'}

        connector = aiohttp.TCPConnector(verify_ssl=False)
        asyncio.ensure_future(_send())


class IncomingMessages(IncomingRequestHandler):
    async def process_request(self, path, query_string, content):
        path = path.split("/")
        conversation_id = path[1]
        if conversation_id is None:
            logger.error("conversation id must be provided as part of path")
            return

        payload = json.loads(content)

        await self.send_data(conversation_id, payload["message"])


def _initialise(bot):
    BridgeInstance(bot, "hubot", IncomingMessages)

