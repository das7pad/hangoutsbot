import asyncio
import json
import logging

import aiohttp

from hangupsbot import plugins
from hangupsbot.sinks import aiohttp_start
from hangupsbot.sinks import AsyncRequestHandler as IncomingRequestHandler


logger = logging.getLogger(__name__)
REQUIRED_ENTRYS = {
    "certfile": str,
    "name": str,
    "port": int,
    "HUBOT_URL": str,
    "synced_conversations": list,
}

class HubotBridge():
    configuration = []
    def __init__(self, bot, configkey, RequestHandler=IncomingRequestHandler):
        self.bot = self._bot = bot
        self.configkey = configkey
        self.RequestHandler = RequestHandler

        if not self._check_config():
            logger.info("no configuration for %s, not running",
                        self.configkey)
            return

        self._start_sinks(bot)

        plugins.register_handler(self._handle_websync)

    def _check_config(self):
        """validate each configured config entry and discard invalid entrys

        Returns:
            bool: True if any config is valid, otherwise False
        """
        input_config = self.bot.get_config_option(self.configkey)
        valid_configs = []
        if not input_config or isinstance(input_config, list):
            return False
        config_nr = 0
        for config in input_config:
            if not isinstance(config, dict):
                logger.warning("config.%s[%s] is not a `dict`",
                               self.configkey, config_nr)
                continue
            for key, expected_type in REQUIRED_ENTRYS.items():
                if not config.get(key):
                    logger.warning('config.%s[%s]["%s"] must be configured',
                                   self.configkey, config_nr, key)
                if not isinstance(config[key], expected_type):
                    logger.warning('config.%s[%s]["%s"] must be of type %s',
                                   self.configkey, config_nr, key,
                                   expected_type.__name__)
            valid_configs.append(config.copy())
            config_nr += 1

        self.configuration = valid_configs
        return bool(valid_configs)

    def _start_sinks(self, bot):
        for listener in self.configuration:
            aiohttp_start(
                bot=bot,
                name=listener["name"],
                port=listener["port"],
                certfile=listener["certfile"],
                requesthandlerclass=self.RequestHandler,
                group="hubotbridge." + self.configkey)

        logger.info("hubotbridge: %s bridges started for %s",
                    len(self.configuration), self.configkey)

    def _handle_websync(self, dummy, event):
        """Handle hangouts messages, preparing them to be sent to the
        external service
        """

        for config in self.configuration:
            convlist = config["synced_conversations"]
            if event.conv_id in convlist:
                self._send_to_external_chat(dummy, event, config)

    @staticmethod
    def _send_to_external_chat(dummy, event, config):
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
        # pylint:disable=unused-argument
        path = path.split("/")
        conversation_id = path[1]
        if conversation_id is None:
            logger.error("conversation id must be provided as part of path")
            return

        payload = json.loads(content)

        yield from self.send_data(conversation_id, payload["message"])


def _initialise(bot):
    HubotBridge(bot, "hubot", IncomingMessages)
