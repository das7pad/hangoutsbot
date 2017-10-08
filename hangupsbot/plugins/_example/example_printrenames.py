"""
example plugin which watches rename events
"""

import logging


logger = logging.getLogger(__name__)


def _initialise(Handlers, bot=None):
    Handlers.register_handler(_watch_rename, "rename")
    return []


async def _watch_rename(bot, event, command):
    # Don't handle events caused by the bot himself
    if event.user.is_self:
        return

    # Only print renames for now...
    if event.conv_event.new_name == '':
        logger.info('%s cleared the conversation name', event.user.first_name)
    else:
        logger.info('%s renamed the conversation to %s',
                    event.user.first_name, event.conv_event.new_name)
