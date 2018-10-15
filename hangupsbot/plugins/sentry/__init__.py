"""Sentry integration

Sentry is an Open-source error tracking that can help you monitor and fix crashes
 in real time.

You can either use their SaaS or on premise service.
"""
__author__ = 'Jakob Ackermann <das7pad@outlook.com>'


import functools
import logging

try:
    from raven import Client
    from raven_aiohttp import AioHttpTransport
except ImportError:
    Client = AioHttpTransport = None
    HAS_RAVEN = False
else:
    HAS_RAVEN = True

from hangupsbot import plugins
from hangupsbot.version import __version__

logger = logging.getLogger(__name__)


def _initialize(bot):
    """

    Args:
        bot:
    """
    if not HAS_RAVEN:
        logger.info('raven is not installed')
        return

    sentry = bot.config.get_option('sentry')
    if not sentry:
        logger.info('Sentry DSN is not specified in the config')
        return

    options = {
        'release': __version__,
    }
    options.update(sentry.get('options', {}))

    client = Client(
        dsn=sentry['dsn'],
        transport=functools.partial(
            AioHttpTransport,
            timeout=30,
        ),
        **options
    )
    plugins.register_aiohttp_session(client.remote.get_transport())
