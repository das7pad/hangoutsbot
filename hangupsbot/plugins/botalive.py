"""plugin to watermark conversations periodically determined by config entry"""

import asyncio
from datetime import datetime
import logging
import random
import hangups.exceptions
import plugins

logger = logging.getLogger(__name__)

def _initialise(bot):
    """setup watermarking plugin

    Args:
        bot: hangupsbot instance
    """
    config_botalive = bot.get_config_option('botalive') or {}
    if not config_botalive:
        return

    if not bot.memory.exists(['conv_data']):
        # should not come to this, but create it once as we need to store data
        #   for each conv in it
        bot.memory.set_by_path(['conv_data'], {})
        bot.memory.save()

    # backwards compatibility
    if isinstance(config_botalive, list):
        _new_config = {}
        if 'admins' in config_botalive:
            _new_config['admins'] = 900
        if 'groups' in config_botalive:
            _new_config['groups'] = 10800
        bot.config.set_by_path(['botalive'], _new_config)
        bot.config.save()
        config_botalive = _new_config

    if 'admins' not in config_botalive and 'groups' not in config_botalive:
        return

    watermark_updater = WatermarkUpdater(bot)

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

    watch_event_types = [
        'message',
        'membership',
        'rename'
        ]
    for event_type in watch_event_types:
        plugins.register_handler(_log_message, event_type)

def _log_message(bot, event):
    """log time to conv_data of event conv

    Args:
        bot: hangupsbot instance, not used
        event: hangups Event instance
    """
    conv_id = str(event.conv_id)
    if not bot.memory.exists(['conv_data', conv_id]):
        bot.memory.set_by_path(['conv_data', conv_id], {})
        bot.memory.save()
    bot.memory.set_by_path(['conv_data', conv_id, 'botalive'],
                           datetime.now().timestamp())
    # not worth a dump to disk, skip bot.memory.save()

@asyncio.coroutine
def _periodic_watermark_update(bot, watermark_updater, target):
    """add conv_ids to the watermark_updater queue and start to process it

    Args:
        bot: hangupsbot instance
        target: 'admins' to add admin 1on1 ids, 'groups' to add group conv_ids
    """

    last_run = datetime.now().timestamp()

    path = ['botalive', target]
    while bot.config.exists(path):
        timestamp = datetime.now().timestamp()
        yield from asyncio.sleep(
            max(5, last_run - timestamp + bot.config.get_by_path(path)))

        if target == 'admins':
            bot_admin_ids = bot.get_config_option('admins')
            for admin in bot_admin_ids:
                if bot.memory.exists(['user_data', admin, '1on1']):
                    conv_id = bot.memory.get_by_path(
                        ['user_data', admin, '1on1'])
                    watermark_updater.add(conv_id)
        else:
            for conv_id, conv_data in bot.conversations.get().items():
                if conv_data['type'] != 'GROUP':
                    continue
                if not bot.memory.exists(['conv_data', conv_id, 'botalive']):
                    continue
                if last_run < bot.memory.get_by_path(
                        ['conv_data', conv_id, 'botalive']):
                    watermark_updater.add(conv_id)

        last_run = datetime.now().timestamp()
        yield from watermark_updater.start()


class WatermarkUpdater:
    """use a queue to update the watermarks sequentially instead of all-at-once

    usage:
    .add(<conv id>) as many conversation ids as you want
    .start() will start processing to queue

    if a hangups exception is raised, log the exception and output to console
    to prevent the processor from being consumed entirely and also to not act
        too much as a bot, we sleep 5-10sec after each watermark update
    """

    def __init__(self, bot):
        self.bot = bot
        self.running = False

        self.queue = set()
        self.failed = dict() # track errors
        self.failed_permanent = set() # track conv_ids that failed 5 times

    def add(self, conv_id):
        """insert a conv_id to the queue if the id is not blacklisted

        Args:
            conv_id: string, id of a conversation
        """
        if conv_id not in self.failed_permanent:
            self.queue.add(conv_id)

    def start(self):
        """start the watermarking if it is not already running"""
        if self.running or not self.queue:
            return
        self.running = True
        yield from self.update_next_conversation()

    @asyncio.coroutine
    def update_next_conversation(self):
        """watermark the next conv, stop the loop if no more ids are present

        if an Exception is raised during the watermarking:
            if the id failed 5 times, blacklist it,
            otherwise
                if the bot still stores the conv in memory:
                    add id to recently failed conv_ids and to the queue
        """
        try:
            conv_id = self.queue.pop()
        except KeyError:
            self.running = False
            return

        logger.info('watermarking %s', conv_id)

        try:
            # pylint:disable=protected-access
            yield from self.bot._client.updatewatermark(
                conv_id, datetime.now())
            self.failed.pop(conv_id, None)

        except hangups.exceptions.NetworkError:
            self.failed[conv_id] = self.failed.get(conv_id, 0) + 1

            if self.failed[conv_id] > 5:
                self.failed_permanent.add(conv_id)
                logger.error('critical error threshold reached for %s', conv_id)
            else:
                logger.exception('WATERMARK FAILED FOR %s', conv_id)

                # is the bot still in the conv
                if conv_id in self.bot.conversations.get():
                    self.add(conv_id)

        yield from asyncio.sleep(random.randint(5, 10))
        yield from self.update_next_conversation()
