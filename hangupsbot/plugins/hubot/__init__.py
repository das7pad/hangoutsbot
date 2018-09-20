import asyncio
import json
import logging

import aiohttp

from hangupsbot import plugins
from hangupsbot.base_models import BotMixin
from hangupsbot.sinks import (
    AsyncRequestHandler as IncomingRequestHandler,
    aiohttp_start,
)


logger = logging.getLogger(__name__)
REQUIRED_ENTRIES = {
    "certfile": str,
    "name": str,
    "port": int,
    "HUBOT_URL": str,
    "synced_conversations": list,
}

class HubotBridge(BotMixin):
    configuration = []
    def __init__(self, config_key, handler_class=IncomingRequestHandler):
        self.config_key = config_key
        self.handler_class = handler_class

        if not self._check_config():
            logger.info("no configuration for %s, not running",
                        self.config_key)
            return

        self._start_sinks()

        plugins.register_handler(self._handle_web_sync)

    def _check_config(self):
        """validate each configured config entry and discard invalid entries

        Returns:
            bool: True if any config is valid, otherwise False
        """
        input_config = self.bot.get_config_option(self.config_key)
        valid_configs = []
        if not input_config or isinstance(input_config, list):
            return False
        config_nr = 0
        for config in input_config:
            if not isinstance(config, dict):
                logger.warning("config.%s[%s] is not a `dict`",
                               self.config_key, config_nr)
                continue
            for key, expected_type in REQUIRED_ENTRIES.items():
                if not config.get(key):
                    logger.warning('config.%s[%s]["%s"] must be configured',
                                   self.config_key, config_nr, key)
                if not isinstance(config[key], expected_type):
                    logger.warning('config.%s[%s]["%s"] must be of type %s',
                                   self.config_key, config_nr, key,
                                   expected_type.__name__)
            valid_configs.append(config.copy())
            config_nr += 1

        self.configuration = valid_configs
        return bool(valid_configs)

    def _start_sinks(self):
        for listener in self.configuration:
            aiohttp_start(
                bot=self.bot,
                name=listener["name"],
                port=listener["port"],
                certfile=listener["certfile"],
                requesthandlerclass=self.handler_class,
                group="hubot_bridge." + self.config_key)

        logger.info("hubot: %s bridges started for %s",
                    len(self.configuration), self.config_key)

    def _handle_web_sync(self, dummy, event):
        """Handle hangouts messages, preparing them to be sent to the
        external service
        """

        for config in self.configuration:
            conv_list = config["synced_conversations"]
            if event.conv_id in conv_list:
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


def _initialise():
    HubotBridge("hubot", IncomingMessages)
