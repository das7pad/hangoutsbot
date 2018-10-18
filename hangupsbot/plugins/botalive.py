"""plugin to watermark conversations periodically determined by config entry"""

import asyncio
import logging
import random
import time
from datetime import (
    datetime,
    timezone,
)

import hangups.exceptions

from hangupsbot import plugins
from hangupsbot.base_models import BotMixin


logger = logging.getLogger(__name__)


def _initialise(bot):
    """setup watermarking plugin

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
    """
    config_botalive = bot.get_config_option('botalive')

    if (not isinstance(config_botalive, dict) or
            not ('admins' in config_botalive or 'groups' in config_botalive)):
        return

    watermark_updater = WatermarkUpdater()

    if 'admins' in config_botalive:
        if config_botalive['admins'] < 60:
            config_botalive['admins'] = 60
        plugins.start_asyncio_task(_periodic_watermark_update,
                                   watermark_updater, 'admins')

    if 'groups' in config_botalive:
        if config_botalive['groups'] < 60:
            config_botalive['groups'] = 60
        plugins.start_asyncio_task(_periodic_watermark_update,
                                   watermark_updater, 'groups')

    logger.info('botalive config %s', config_botalive)


async def _periodic_watermark_update(bot, watermark_updater, target):
    """add conv_ids to the watermark_updater queue and start to process it

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        target (str): 'admins' to enqueue chats with admins or 'groups' to
            enqueue group chats
    """
    last_run = time.time()

    path = ['botalive', target]
    try:
        while bot.config.exists(path):
            timestamp = time.time()
            await asyncio.sleep(
                max(5, last_run - timestamp + bot.config.get_by_path(path)))

            if target == 'admins':
                bot_admin_ids = bot.get_config_option('admins')
                for admin in bot_admin_ids:
                    admin_1on1 = ['user_data', admin, '1on1']
                    if bot.memory.exists(admin_1on1):
                        conv_id = bot.memory.get_by_path(admin_1on1)
                        watermark_updater.add(conv_id, overwrite=True)
            else:
                for conv_id in bot.conversations.get('type:group'):
                    watermark_updater.add(conv_id)

            last_run = time.time()
            await watermark_updater.start()
    except asyncio.CancelledError:
        return


class WatermarkUpdater(BotMixin):
    """use a queue to update the watermarks sequentially instead of all-at-once

    .add(<conv id>, overwrite=<boolean>) queue conversations for a watermark
    .start() start processing of the queue

    if a hangups exception is raised, log the exception and drop a conversation
        from watermarking after N retries
        N is set in config with the key 'permafail' and defaults to 5 retries

    to prevent the processor from being consumed entirely and also to not act
        too much as a bot, we sleep 5 to T seconds after each watermark update
        T is set in config with the key 'maxfuzz' and defaults to 10 seconds
    """

    def __init__(self):
        self._lock = asyncio.Lock()

        self.queue = set()
        self.failed = dict()  # track errors
        self.failed_permanent = set()  # track conv_ids that failed 5 times

        self.bot.config.set_defaults({'maxfuzz': 10, 'permafail': 5},
                                     path=['botalive'])

    def add(self, conv_id, overwrite=False):
        """schedule a conversation for watermarking and filter blacklisted

        Args:
            conv_id (str): id of a conversation
            overwrite (bool): toggle to update the watermark even when there
                were no new events in the conversations
        """
        if conv_id not in self.failed_permanent:
            self.queue.add((conv_id, overwrite))

    async def start(self):
        """process the watermarking queue"""
        if self._lock.locked():
            return
        async with self._lock:
            delay_path = ['botalive', 'maxfuzz']
            delay = self.bot.config.get_by_path(delay_path)
            while self.queue:
                await asyncio.sleep(random.randint(5, delay))
                await asyncio.shield(self._update_next_conversation())

    async def _update_next_conversation(self):
        """watermark the next conv, stop the loop if no more ids are present

        blacklist a conversation after five failed watermark attempts
        """
        conv_id, overwrite = self.queue.pop()
        read_timestamp = datetime.now(timezone.utc) if overwrite else None

        logger.debug('watermarking %s %s',
                     conv_id, 'explicit' if overwrite else 'if needed')
        try:
            # pylint:disable=protected-access
            await self.bot._conv_list.get(conv_id).update_read_timestamp(
                read_timestamp=read_timestamp)
        except KeyError:
            logger.debug('conversation %s already left', conv_id)
        except hangups.exceptions.NetworkError as err:
            if 'Former member' in repr(err):
                self.failed.pop(conv_id, None)
                self.bot.conversations.remove(conv_id)
                return

            logger.info(
                'watermark failed %s: conversation %s',
                id(err), conv_id
            )
            logger.error(
                'watermark failed %s: %r',
                id(err), err
            )

            self.failed[conv_id] = self.failed.get(conv_id, 0) + 1

            limit = self.bot.config.get_by_path(['botalive', 'permafail'])
            if self.failed[conv_id] > limit:
                self.failed.pop(conv_id)
                self.failed_permanent.add(conv_id)
                logger.warning(
                    'critical error threshold reached for %s',
                    conv_id
                )
        else:
            self.failed.pop(conv_id, None)
