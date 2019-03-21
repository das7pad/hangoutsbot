"""web hook broadcast

Broadcast messages as serialized json payload to web hooks

config:
    'webhook': {
        'key_for_logs_and_memory': {
            'url': 'URL',
        }
        'other_key_for_logs_and_memory': {
            'url': 'URL',
            'params': {
                'aiohttp.request_param': value,
            }
        },
        'yet_another_key_for_logs_and_memory': {
            'url': 'http://example.com/secret/endpoint',
            'params': {
                'headers': {
                    'X-Secret': 'MAGIC',
                },
            }
        },
    }

memory:
    'webhook': {
        'key_for_logs_and_memory': [
            'hangouts:conv_id_0',
        ],
        'other_key_for_logs_and_memory': [
            'hangouts:conv_id_0',
            'telesync:123',
        ],
    }
"""
__author__ = 'Jakob Ackermann <das7pad@outlook.com>'

import asyncio
import logging

import aiohttp

from hangupsbot import plugins
from hangupsbot.base_models import BotMixin
from hangupsbot.version import __version__


logger = logging.getLogger(__name__)
DEFAULT_HEADER = {
    'X-Powered-By': 'hangupsbot (%s)' % __version__,
}


async def _initialize(bot):
    """setup the hooks

    Args:
        bot (hangupsbot.core.HangupsBot): running instance
    """
    web_hooks = bot.config.get_option('webhook')
    if not web_hooks:
        logger.info('No outgoing web hooks configured')
        return

    valid_web_hooks = _get_valid_web_hooks(web_hooks)

    for name, config in valid_web_hooks.items():
        handler = Handler(
            name=name,
            target=config['url'],
            params=config['params'],
        )
        await handler.start()


def _get_logger(name):
    return logging.getLogger(__name__ + '.' + name)


def _check_config(config):
    if not isinstance(config, dict):
        return 'expected config type of dict, got %s' % type(config)
    if 'url' not in config:
        return "required config item 'url' is missing"
    if 'params' in config and not isinstance(config['params'], dict):
        return (
            "expected config item 'params' type of dict, got %s"
            % type(config['params'])
        )
    return None


def _get_valid_web_hooks(web_hooks) -> dict:
    if not isinstance(web_hooks, dict):
        logger.info('Invalid format for outgoing web hooks, check the docs')
        return {}

    valid_web_hooks = {}

    for name, config in web_hooks.items():
        invalid_spec = _check_config(config)

        if invalid_spec:
            _get_logger(name).info(
                'Invalid format, check the docs: %s',
                invalid_spec
            )
            continue

        full_config = {
            'params': {},
        }
        full_config.update(config)
        valid_web_hooks[name] = full_config

    return valid_web_hooks


class Handler(BotMixin):
    def __init__(self, name, target, params):
        self._logger = _get_logger(name)
        self._name = name
        self._target = target
        self._params = params
        self._session = None  # type: aiohttp.ClientSession

        self.bot.memory.set_defaults({self._name: []}, ['webhook'])

    async def _set_session(self):
        headers = self._params.pop('headers', {})
        headers.update(DEFAULT_HEADER)
        self._session = aiohttp.ClientSession(
            headers=headers,
        )

    async def start(self):
        await self._set_session()
        plugins.register_aiohttp_session(self._session)
        plugins.register_sync_handler(
            self._handle_message,
            name='allmessages_once'
        )

    async def _handle_message(self, bot, event):
        """process an event

        Args:
            bot (hangupsbot.core.HangupsBot): the running instance
            event (hangupsbot.sync.event.SyncEvent): an event
        """
        sources = bot.memory.get_by_path(['webhook', self._name])
        if event.identifier not in sources:
            return

        await self.send_message(event)

    @staticmethod
    def serialize_reply(reply=None):
        """serialize a reply

        Args:
            reply (hangupsbot.sync.event.SyncReply): a reply, optional

        Returns:
            dict: json data
        """
        if not reply:
            return {}

        return {
            'offset': reply.offset,
            'user_identifier': reply.user.identifier,
            'user_name': reply.user.full_name,
            'text': reply.text,
        }

    @classmethod
    async def serialize_event(cls, event):
        """serialize an event

        Args:
            event (hangupsbot.sync.event.SyncEvent): an event

        Returns:
            dict: json data
        """
        return {
            'conv_id': event.conv_id,
            'edited': event.edited,
            'image_type': event.image.type_ if event.image else None,
            'image_url': await event.get_image_url(),
            'reply': cls.serialize_reply(event.reply),
            'segments': [seg.serialize() for seg in event.conv_event.segments],
            'text': event.text,
            'user_identifier': event.user.identifier,
            'user_name': event.user.full_name,
        }

    async def send_message(self, event):
        """send an event

        Args:
            event (hangupsbot.sync.event.SyncEvent): an event
        """
        message = await self.serialize_event(event)
        await self.send(message)

    async def send(self, message):
        """post the message to the web hook

        Args:
            message (dict): json body

        Raises:
            asyncio.CancelledError: message sending got cancelled
        """
        self._logger.info(
            'sending message %s: %r',
            id(message), message
        )
        try:
            await self._session.post(
                self._target,
                json=message,
                **self._params
            )
        except asyncio.CancelledError:
            self._logger.info(
                'sending message %s: cancelled',
                id(message)
            )
            raise
        except aiohttp.ClientError as err:
            self._logger.error(
                'send message %s: failed %r',
                id(message), err
            )
