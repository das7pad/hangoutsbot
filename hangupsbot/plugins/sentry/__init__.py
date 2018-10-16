"""Sentry integration

Sentry is an Open-source error tracking that can help you monitor and fix crashes
 in real time.

You can either use their SaaS or on premise service.
"""
__author__ = 'Jakob Ackermann <das7pad@outlook.com>'


import functools
import logging
import os

try:
    from raven import Client
    from raven_aiohttp import AioHttpTransport
except ImportError:
    logging.getLogger(__name__).info('raven and raven_aiohttp are required')
    raise

from hangupsbot import plugins
from hangupsbot.version import __version__

logger = logging.getLogger(__name__)


def _initialize(bot):
    """

    Args:
        bot:
    """
    sentry = bot.config.get_option('sentry')
    if not isinstance(sentry, dict):
        sentry = {}

    if 'dsn' in sentry:
        dsn = sentry['dsn']
    else:
        if 'SENTRY_DSN' not in os.environ:
            logger.info('Sentry is not configured')
            return
        logger.info('Using Sentry DSN from environment')
        dsn = os.environ['SENTRY_DSN']

    options = {
        'release': __version__,
    }
    options.update(sentry.get('options', {}))

    client = Client(
        dsn=dsn,
        transport=functools.partial(
            AioHttpTransport,
            timeout=30,
        ),
        **options
    )

    if not client.is_enabled():
        logging.warning('Reporting to Sentry is disabled')
        return
    logging.warning('Reporting to Sentry is enabled')

    plugins.register_aiohttp_session(client.remote.get_transport())
