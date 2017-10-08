import asyncio
import json
import logging

import aiohttp

import plugins

from sinks import aiohttp_start
from sinks import AsyncRequestHandler as IncomingRequestHandler


logger = logging.getLogger(__name__)


class HubotBridge():
    def __init__(self, bot, configkey, RequestHandler=IncomingRequestHandler):
        self.bot = self._bot = bot
        self.configkey = configkey
        self.RequestHandler = RequestHandler
        self.configuration = bot.get_config_option(self.configkey)

        if not self.configuration:
            logger.info("no configuration for %s, not running",
                        self.configkey)
            return

        self._start_sinks(bot)

        plugins.register_handler(self._handle_websync)

    def _start_sinks(self, bot):

        itemNo = -1

        if isinstance(self.configuration, list):
            for listener in self.configuration:
                itemNo += 1

                try:
                    certfile = listener["certfile"]
                    if not certfile:
                        logger.warning(
                            "config.%s[%s].certfile must be configured",
                            self.configkey, itemNo)
                        continue
                    name = listener["name"]
                    port = listener["port"]
                except KeyError:
                    logger.warning("config.%s[%s] missing keyword",
                                   self.configkey, itemNo)
                    continue

                aiohttp_start(
                    bot=bot,
                    name=name,
                    port=port,
                    certfile=certfile,
                    requesthandlerclass=self.RequestHandler,
                    group="hubotbridge." + self.configkey)

        logger.info("hubotbridge.sinks: %s thread(s) started for %s",
                    itemNo + 1, self.configkey)

    def _handle_websync(self, bot, event, command):
        """Handle hangouts messages, preparing them to be sent to the
        external service
        """

        if isinstance(self.configuration, list):
            for config in self.configuration:
                try:
                    convlist = config["synced_conversations"]
                    if event.conv_id in convlist:
                        self._send_to_external_chat(bot, event, config)
                except:
                    logger.exception("EXCEPTION in _handle_websync")

    @staticmethod
    def _send_to_external_chat(bot, event, config):
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
        asyncio.ensure_future(
            aiohttp.request('post', url, data=json.dumps(payload),
                            headers=headers, connector=connector)
        )


class IncomingMessages(IncomingRequestHandler):
    @asyncio.coroutine
    def process_request(self, path, query_string, content):
        path = path.split("/")
        conversation_id = path[1]
        if conversation_id is None:
            logger.error("conversation id must be provided as part of path")
            return

        payload = json.loads(content)

        yield from self.send_data(conversation_id, payload["message"])


def _initialise(bot):
    HubotBridge(bot, "hubot", IncomingMessages)
