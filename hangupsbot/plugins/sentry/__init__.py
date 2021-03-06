"""Sentry integration

Sentry is an Open-source error tracking that can help you monitor and fix crashes
 in real time.

You can either use their SaaS or on premise service.

The configuration can be a mixture of config and environment variables.
    - config:
        'sentry': {
            'dsn': str, a Sentry DSN,
            'level': int, logging level that triggers the sending
            'breadcrumbs_level', int, minimum logging level for breadcrumbs
            'options': {
                'auto_log_exc_info': bool, replace generic tb with exception tb
                'enable_breadcrumbs': bool, track previous log messages,
                'capture_locals': bool, include local variables in a traceback
                NOTE: this may send user data to your sentry provider.

            see Raven Client documentation for more
            }
        }
    - environment:
        'SENTRY_DSN': str, a Sentry DSN
    for more environment variables see Raven Client documentation
"""
__author__ = 'Jakob Ackermann <das7pad@outlook.com>'


import functools
import logging
import os

try:
    from raven import Client
    import raven.base
    import raven.breadcrumbs
    import raven.conf
    from raven.handlers.logging import SentryHandler

    from raven_aiohttp import AioHttpTransport
except ImportError:
    logging.getLogger(__name__).info('raven and raven_aiohttp are required')
    raise

from hangupsbot import plugins
from hangupsbot.version import __version__

logger = logging.getLogger(__name__)


def _initialize(bot):
    """setup the sentry integration

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
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
        'auto_log_exc_info': True,
        'enable_breadcrumbs': False,
        'capture_locals': False,
    }
    options.update(sentry.get('options', {}))

    raven.base.Raven = None
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

    level = sentry.get('level', logging.ERROR)
    setup_global_logger(client, level)

    block_internal_log_messages()
    setup_breadcrumbs_handler(
        send_level=sentry.get('breadcrumbs_level', logging.INFO),
    )


def block_internal_log_messages():
    """block the processing of log messages from raven"""
    internal_logger = (
        'raven',
        'sentry.errors',
    )
    for name in internal_logger:
        instance = logging.getLogger(name)
        instance.propagate = False


def setup_global_logger(client, level):
    """cleanup old logger, add a new instance

    Args:
        client (raven.base.Client): the current instance
        level (int): the minimum level that triggers event sending
    """
    # remove a previous instance
    current = logging.getLogger().handlers
    for handler in current.copy():
        if isinstance(handler, SentryHandler):
            current.remove(handler)

    raven.conf.setup_logging(SentryHandler(client, level=level), exclude=())


def setup_breadcrumbs_handler(send_level):
    """cleanup old handler, add a new logging handler

    Args:
        send_level (int): the minimum level that triggers sending
    """
    # remove old handler
    raven.breadcrumbs.special_logging_handlers.clear()

    def level_filter(_logger, level, _msg, _args, _kwargs):
        return level < send_level

    # ignore a message in case a logging handler returned True
    raven.breadcrumbs.register_logging_handler(level_filter)
