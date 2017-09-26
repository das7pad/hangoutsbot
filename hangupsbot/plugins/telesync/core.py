"""Telepot sync-bot"""
__author__ = 'das7pad@outlook.com'

import asyncio
import io
import json
import logging
import time
import random

import aiohttp
import telepot
import telepot.aio
import telepot.aio.api
import telepot.exception
from telepot.loop import _extract_message

import plugins

from sync.parser import get_formatted
from sync.sending_queue import AsyncQueueCache

from .commands_tg import (
    command_whoami,
    command_whereami,
    command_set_sync_ho,
    command_clear_sync_ho,
    command_add_admin,
    command_remove_admin,
    command_sync_profile,
    command_unsync_profile,
    command_tldr,
    command_get_me,
    command_start,
    command_get_admins,
    command_echo,
    command_leave,
    command_cancel,
    command_chattitle,
    command_sync_config,
    command_restrict_user,
)

from .message import Message
from .parsers import TelegramMessageSegment
from .user import User

logger = logging.getLogger(__name__)

# attach the pools to cancel them later gracefully
POOLS = telepot.aio.api._pools  # pylint: disable=protected-access

# check the connection pools for a running connector
if 'default' not in POOLS or POOLS['default'].closed:
    logger.info('adding a new default connection pool')
    POOLS['default'] = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=10))

IGNORED_MESSAGE_TYPES = (
    'migrate_from_chat_id',                  # duplicate of 'migrate_to_chat_id'
)

class TelegramBot(telepot.aio.Bot):
    """enhanced telepot bot with Hangouts sync

    Args:
        ho_bot: HangupsBot instance
    """

    def __init__(self, ho_bot):
        self.bot = Message.bot = ho_bot
        Message.tg_bot = self
        self.user = None
        self._receive_next_updates = 0

        api_key = self.config('api_key', False)
        super().__init__(api_key)

        self._cache_sending_queue = AsyncQueueCache('telesync', self._send_html,
                                                    bot=ho_bot)
        self._cache_sending_queue.start()

        self._commands = {'/whoami': command_whoami,
                          '/whereami': command_whereami,
                          '/setsyncho': command_set_sync_ho,
                          '/clearsyncho': command_clear_sync_ho,
                          '/addadmin': command_add_admin,
                          '/removeadmin': command_remove_admin,
                          '/syncprofile': command_sync_profile,
                          '/unsyncprofile': command_unsync_profile,
                          '/tldr': command_tldr,
                          '/getme': command_get_me,
                          '/start': command_start,
                          '/getadmins': command_get_admins,
                          '/echo': command_echo,
                          '/leave': command_leave,
                          '/cancel': command_cancel,
                          '/chattitle': command_chattitle,
                          '/sync_config': command_sync_config,
                          '/restrict_user': command_restrict_user,
                         }

    def config(self, key=None, fallback=True):
        """get a telegram config entry

        Args:
            key: string, an item in the telesync config
            fallback: boolean, toggle to use the config defaults on missing keys

        Returns:
            any type, the requested item; dict, entire config if no key is set
        """
        item = [key] if key is not None else []
        return self.bot.config.get_by_path(['telesync'] + item, fallback)

    async def start(self, dummy=None):
        """init the bot user and commands, start the reminder and MessageLoop

        Args:
            dummy: HangupsBot instance, arg is required for a registered task
        """
        bot_user = await self.getMe()
        bot_chat_id = self.bot.user_self()['chat_id']
        self.bot.memory.set_defaults(
            {bot_user['id']: bot_chat_id},
            path=['profilesync', 'telesync', '2ho'])

        self.user = User(self, {'bot': bot_user, 'chat': {'id': None}},
                         chat_action='bot')
        logger.info('Botuser: id: %s, name: %s, username: %s',
                    self.user.usr_id, self.user.first_name, self.user.username)

        tasks = [
            asyncio.ensure_future(self._periodic_profile_updater()),
            asyncio.ensure_future(self._periodic_profilesync_reminder()),
        ]

        try:
            await self._message_loop()
        except asyncio.CancelledError:
            return
        except telepot.exception.UnauthorizedError:
            logger.critical('API-Key revoked!')
        finally:
            await self._cache_sending_queue.stop(timeout=5)

            # cancel housekeeping tasks
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            try:
                # discard the last few message
                old_messages = [item['update_id']
                                for item in await self.getUpdates(offset=-1)]
                if old_messages:
                    logger.info('discard the updates %s', old_messages)
                    await self.getUpdates(offset=max(old_messages) + 1)
            except telepot.exception.TelegramError as err:
                logger.warning('discard of last messages failed: %s', str(err))

    async def is_running(self, retry=True):
        """check if Telegram api requests can be made

        Args:
            retry: boolean, toggle to allow a single retry on a Server Error

        Returns:
            boolean, True if the TelegramBot is running, otherwise False
        """
        if self._receive_next_updates > time.time():
            return True

        try:
            await self.getMe()
        except telepot.exception.UnauthorizedError:
            logger.critical('API-KEY is not valid, unloading the plugin')
            asyncio.ensure_future(plugins.unload(self.bot, 'plugins.telesync'))
            retry = False
        except telepot.exception.TooManyRequestsError as err:
            delay = err.json.get('parameters', {}).get('retry_after', 60)
            logger.warning('too many requests! received a delay=%s', delay)
            await asyncio.sleep(delay)
            return True
        except telepot.exception.BadHTTPResponse as err:
            if err.status >= 500:
                message = 'a Telegram server error'
            else:
                message = 'an unexpected response'
            logger.error('getMe received %s: %d - %s',
                         message, err.status, err.text)
            await asyncio.sleep(10)
            if retry:
                return await self.is_running(retry=False)
        except (telepot.exception.TelegramError, aiohttp.ClientError) as err:
            logger.info('getMe: %s', repr(err))
        else:
            return True

        if retry:
            logger.warning('not running, reloading the plugin')
            # detach the execution as the current call will be cancelled soon
            asyncio.ensure_future(
                plugins.reload_plugin(self.bot, 'plugins.telesync'))
        return False

    def send_html(self, tg_chat_id, html):
        """send html to telegram chat keeping the sequence

        Args:
            tg_chat_id: int, a chat the bot user has access to
            html: string, nested html tags are not allowed

        Returns:
            a `sync.sending_queue.Status` instance for the scheduled task which
            can be awaited for a boolean value, returned as the task completed:
                True on success otherwise False
        """
        queue = self._cache_sending_queue.get(tg_chat_id)
        return queue.schedule(tg_chat_id, html)

    async def get_tg_user(self, user_id, chat_id=None, gpluslink=False,
                          use_cache=True):
        """get a User matching the user_id in a chat with chat_id

        user data can only be fetched, if a chat with the user exists

        Args:
            user_id: string, user identifier
            chat_id: string, telegram chat identifier
            gpluslink: boolean, set to True get G+Links instead of t.me links
            use_cache: boolean, set to False to ignore a cache hit and to
             perform an API request for updated user data

        Returns:
            User, a subclass of sync.user.SyncUser
        """
        path_user = ['telesync', 'user_data', user_id]

        if self.bot.memory.exists(path_user):
            tg_user = self.bot.memory.get_by_path(path_user)
            chat_id = chat_id or tg_user['last_seen']
        else:
            tg_user = None

        if not (use_cache and tg_user is not None):
            if chat_id is not None:
                logger.debug('fetch user %s in %s', user_id, chat_id)
                try:
                    response = await self.getChatMember(chat_id, user_id)
                    tg_user = response.get('user')
                except telepot.exception.TelegramError:
                    if user_id != chat_id:
                        # the user is likely a former member, remove him
                        try:
                            self.bot.memory.pop_by_path(
                                ['telesync', 'chat_data',
                                 str(chat_id), str(user_id)])
                        except KeyError:
                            logger.warning(
                                'failed to remove user %s from chat %s',
                                user_id, chat_id)
                            tg_user['last_seen'] = None
                            chat_id = None

            if tg_user is None:
                tg_user = {'id': user_id, 'first_name': 'unknown'}
        user = User(self, {'user': tg_user, 'chat': {'id': chat_id}},
                    chat_action='user', gpluslink=gpluslink)
        await user.update_user_picture(use_cache=use_cache)
        return user

    async def get_image(self, image, type_='photo', extension=None):
        """download an image from Telegram and create a SyncImage

        Args:
            image: dict, media item from telegram
            type_: string, 'photo', 'sticker', 'gif', 'video'
            exception: string, opt, file extension

        Returns:
            sync.SyncImage instance or None if no image could be created
        """
        image_data = io.BytesIO()
        try:
            await self.download_file(image['file_id'], image_data)
        except telepot.exception.TelegramError:
            logger.exception('image download of %s failed', image)
            return None

        if extension is not None:
            # override
            pass
        elif type_ == 'photo':
            extension = 'jpg'
        elif type_ == 'sticker':
            extension = 'webm'
        else:
            extension = 'mp4'

        filename = '{name}.{ext}'.format(name=image['file_id'], ext=extension)

        size = ((image['width'], image['height'])
                if 'width' in image and 'height' in image else None)

        image = self.bot.sync.get_sync_image(data=image_data, filename=filename,
                                             type_=type_, size=size)
        logger.info('filename %s | extension %s | type_ %s',
                    filename, extension, type_)

        if extension != 'mp4' or type_ == 'video':
            return image

        # telegram converts gifs to videos, we have to do that in reverse
        await image.process()

        image._data, image._filename = image.get_data(video_as_gif=True)
        return image

    async def profilesync_info(self, user_id, is_reminder=False):
        """send info about pending profilesync to user

        Args:
            user_id: str, identifier for the user and its 1on1 chat with the bot
            is_reminder: bool, set to True to prepend the reminder flag
        """
        bot = self.bot
        path = ['profilesync', 'telesync', 'pending_2ho', user_id]
        if not bot.memory.exists(path):
            return
        token = bot.memory.get_by_path(path)

        if is_reminder:
            html = _('<b> [ REMINDER ] </b>\n')
        else:
            html = ''

        bot_cmd = self.bot.command_prefix

        html += _(
            '<b>Please send me one of the messages below</b> <a href="'
            'https://hangouts.google.com/chat/person/{bot_id}">in Hangouts</a>:'
            '\nNote: The message must start with <b>{bot_cmd}</b>, otherwise I '
            'do not process your message as a command and ignore your message.'
            '\nIf you copy the message below, Telegram might add <b>{name}:</b>'
            ' to my message. Just delete that until the message starts with <b>'
            '{bot_cmd}</b>.\n'
            'Our private Hangout and this chat will be automatically synced. You'
            ' can then receive mentions and other messages I only send to '
            'private Hangouts. Use <i>split</i>  next to the token to block '
            'this sync.\n'
            'Use /unsyncprofile to cancel the process.'
            ).format(bot_cmd=bot_cmd, bot_id=self.bot.user_self()['chat_id'],
                     name=self.user.first_name)

        if not await self.send_html(user_id, html):
            base_path = ['profilesync', 'telesync']
            token = bot.memory.pop_by_path(base_path + ['pending_2ho', user_id])
            bot.memory.pop_by_path(base_path + ['pending_ho2', token])
            bot.memory.pop_by_path(['profilesync', '_pending_', token])
            return

        self.send_html(user_id, '{} syncprofile {}'.format(bot_cmd, token))
        self.send_html(user_id, '{} syncprofile {} <i>split</i>'.format(bot_cmd,
                                                                        token))

    async def _send_html(self, tg_chat_id, text, as_html=True, silent=False):
        """send html to telegram chat

        Args:
            tg_chat_id: int, a chat the bot user has access to
            text: string, nested html tags are not allowed
            silent: boolean, set to True to disable a client notification

        Returns:
            boolean, True in case of a successful api-call, otherwise False
        """
        if not await self.is_running() or not text:
            return False

        text = get_formatted(text, 'html_flat', internal_source=True)

        if len(text) > 4095:
            first_part = text[:4095].rsplit('\n', 1)[0]
            next_part = text[len(first_part):]
            text = first_part
        else:
            next_part = None

        try:
            msg = await self.sendMessage(tg_chat_id, text,
                                         parse_mode='HTML' if as_html else None,
                                         disable_web_page_preview=True,
                                         disable_notification=silent)

        except telepot.exception.TooManyRequestsError as err:
            delay = err.json.get('parameters', {}).get('retry_after')
            logger.warning('too many requests! received a delay of %s', delay)
            await asyncio.sleep(int(delay or 60))
            status = await self._send_html(tg_chat_id, text, as_html, silent)

        except telepot.exception.TelegramError as err:
            status = False
            if ('chat not found' in err.description
                    or 'bot was blocked by the user' in err.description):
                logger.error('%s: "%s"', err.description, tg_chat_id)
                next_part = None
            elif 'can\'t parse entities in message text' in err.description:
                logger.info('html failed in %s, content: %s', tg_chat_id, text)
                status = await self._send_html(tg_chat_id,
                                               get_formatted(text, 'text'),
                                               as_html=False, silent=silent)
            else:
                logger.error('sending of "%s" to "%s" failed:\n%s',
                             text, tg_chat_id, repr(err))

        else:
            Message.add_message(tg_chat_id, msg.get('message_id'))
            status = True

        finally:
            if next_part is not None:
                status = await self._send_html(tg_chat_id, next_part,
                                               as_html=as_html, silent=True)
        return status

    def _parse_command(self, msg):
        """get cmd and assigned bot_name

        valid pattern:
        /command
        /command args
        /command@name_bot args

        Args:
            msg: Message
        Returns:
            tuple of bool, string and list of strings:
                command is valid, command, args
        """
        if not msg.text.startswith('/'):
            return False, '', []
        txt_split = msg.text.replace('\\_', '_').split()
        cmd, is_addressed, name = txt_split[0].partition('@')
        if is_addressed and name.lower() != self.user.username.lower():
            return False, '', []
        return cmd.lower() in self._commands, cmd, txt_split[1:]

    async def _handle(self, response):
        """check event type and route message to target functions

        only process event type 'chat'

        Args:
            response: dict, api-response from telepot
        """
        logger.debug(response)
        if 'migrate_to_chat_id' in response:
            self._on_supergroup_upgrade(response)
            return

        if (telepot.flavor(response) != 'chat'
                or any(key in response for key in IGNORED_MESSAGE_TYPES)):
            return

        msg = Message(response)

        if msg.content_type == 'text':
            valid, cmd, params = self._parse_command(msg)
            if valid and not await self._commands[cmd](self, msg, *params):
                # the command is valid and the command shall not be synced
                return

        if msg.content_type in ('new_chat_member', 'new_chat_members',
                                'left_chat_member'):
            self._on_membership_change(msg)

        else:
            await self._forward_content(msg)

    async def _forward_content(self, msg):
        """message handler for text, photo, sticker, location

        Args:
            msg: Message instance
        """
        bot = self.bot
        chat_id = msg.chat_id
        if bot.memory.exists(['telesync', 'tg2ho', chat_id]):
            ho_conv_ids = bot.memory.get_by_path(['telesync', 'tg2ho', chat_id])

        elif bot.memory.exists(['telesync', 'channel2ho', chat_id]):
            ho_conv_ids = bot.memory.get_by_path(
                ['telesync', 'channel2ho', chat_id])

            msg.user.is_self = True

        else:
            # no sync target set for this chat
            return

        if msg.image_info is not None:
            image = await self.get_image(*msg.image_info)
        else:
            image = None

        if msg.user.photo_url is None:
            await msg.user.update_user_picture()

        logger.debug('forwarding %s from: %s to %s',
                     msg.content_type, msg.chat_id, ho_conv_ids)

        segments = TelegramMessageSegment.from_str((msg.text,
                                                    msg.get('entities', [])))

        for conv_id in ho_conv_ids:
            asyncio.ensure_future(self.bot.sync.message(
                identifier='telesync:' + msg.chat_id, conv_id=conv_id,
                user=msg.user, text=segments,
                reply=await msg.get_reply(), image=image,
                title=msg.get_group_name(), edited=msg.edited))

    def _on_membership_change(self, msg):
        """forward a membership change

        Args:
            msg: Message instance
        """
        bot = self.bot
        if not bot.memory.exists(['telesync', 'tg2ho', msg.chat_id]):
            # no sync target set for this chat
            return
        ho_conv_ids = bot.memory.get_by_path(['telesync', 'tg2ho', msg.chat_id])

        if 'new_chat_members' in msg:
            raw_users = msg['new_chat_members']
            changed_members = []
            for raw_user in raw_users:
                msg['_user_'] = raw_user
                changed_members.append(User(self, msg, chat_action='_user_'))
        else:
            changed_members = [User(self, msg, chat_action=msg.content_type)]

        for changed_member in changed_members:
            path_chat = ['telesync', 'chat_data', msg.chat_id, 'user',
                         changed_member.usr_id]
            if msg.content_type == 'left_chat_member':
                type_ = 2
                if bot.memory.exists(path_chat):
                    bot.memory.pop_by_path(path_chat)

                path_last_seen = ['telesync', 'user_data',
                                  changed_member.usr_id, 'last_seen']
                if str(bot.memory.get_by_path(path_last_seen)) == msg.chat_id:
                    bot.memory.set_by_path(path_last_seen, None)
            else:
                bot.memory.set_by_path(path_chat, 1)
                type_ = 1

        bot.memory.save()

        participant_user = ([] if (len(changed_members) == 1 and
                                   msg.user.usr_id == changed_members[0].usr_id)
                            else changed_members)

        logger.info('membership change [%s] in %s: <"%s">%s%s',
                    msg.content_type, msg.chat_id,
                    '">, <"'.join(user.full_name for user in changed_members),
                    ' triggered by ' if participant_user else '',
                    msg.user.full_name if participant_user else '')

        for conv_id in ho_conv_ids:
            asyncio.ensure_future(bot.sync.membership(
                identifier='telesync:' + msg.chat_id, conv_id=conv_id,
                user=msg.user, title=msg.get_group_name(), type_=type_,
                participant_user=participant_user))

    def _on_supergroup_upgrade(self, msg):
        """migrate all old data to a new chat id

        Args:
            msg: dict, message from Telegram
        """
        bot = self.bot

        old_chat_id = str(msg['chat']['id'])
        new_chat_id = str(msg['migrate_to_chat_id'])

        # migrate syncs and conv data
        old_data = json.dumps(bot.memory['telesync'])
        new_data = json.loads(old_data.replace('"%s"' % old_chat_id,
                                               '"%s"' % new_chat_id))
        bot.memory['telesync'] = new_data
        bot.memory.save()

        # migrate config
        old_config = bot.config['conversations'].pop('telesync:' + old_chat_id,
                                                     None)
        if old_config is not None:
            bot.config['conversations']['telesync:' + new_chat_id] = old_config
            bot.config.save()

        logger.info('group %s upgraded to Supergroup %s',
                    old_chat_id, new_chat_id)

    async def _periodic_profilesync_reminder(self):
        """remind users to finish pending profilesyncs

        sleep for x hours before each notify run
        x determined by telesync config entry 'profilesync_reminder'
        """
        path = ['profilesync', 'telesync', 'pending_2ho']
        try:
            while 'profilesync_reminder' in self.config():
                # to prevent spam on reboots, rather sleep before notify users
                await asyncio.sleep(3600 * self.config('profilesync_reminder'))

                for user_id in self.bot.memory.get_by_path(path).copy():
                    await self.profilesync_info(user_id, is_reminder=True)
        except asyncio.CancelledError:
            return
        except:                                    # pylint: disable=bare-except
            logger.exception('lowlevel error in periodic profilesync reminder')

    async def _periodic_profile_updater(self):
        """update the telesync data periodically

        sleep for x hours after each update run
        x determined by telesync config entry 'profile_update_intervall'

        this could likely end in a ratelimit, delay each query by 10-20 seconds
        """
        data_path = ['telesync', 'user_data']
        chat_path = ['telesync', 'chat_data']
        memory = self.bot.memory
        try:
            while True:

                # update last_seen values
                for chat_id, data in memory.get_by_path(chat_path).items():
                    for user_id in data.get('users', ()):
                        memory.set_by_path(data_path + [user_id, 'last_seen'],
                                           chat_id)

                for user_id in memory.get_by_path(data_path).copy():
                    await self.get_tg_user(user_id=user_id, use_cache=False)
                    await asyncio.sleep(random.randint(10, 20))

                await asyncio.sleep(
                    3600 * self.config('profile_update_intervall'))
        except asyncio.CancelledError:
            return
        except:                                    # pylint: disable=bare-except
            logger.exception('lowlevel error in profile updater')

    async def _message_loop(self):
        """long polling for updates and handle errors gracefully

        Raises:
            telepot.exception.UnauthorizedError: API-token invalid
        """
        def _log_http_error(delay, error):
            """log a custom error message for an error

            Args:
                delay: float, previous delay between to requests
                error: tuple, (Exception instance, status code, error message)

            Returns:
                float, new delay between to requests
            """
            if error[1] >= 500:
                delay = 30.
                flat = repr(error).lower()
                reason = ('server restart' if 'restart' in flat else
                          'pending server restart' if 'gateway' in flat else
                          error[2])
                message = 'Telegram server error', reason
            elif error[1]:
                message = 'Unexpected response', error[2]
            else:
                message = 'Unexpected error', error[2]
            logger.error('%s in message loop: %s', *message)
            return delay

        async def _handle_update(update):
            """extract and handle a message of an `Update`

            Args:
                update (dict): see `https://core.telegram.org/bots/api#update`

            Returns:
                boolean: True in case the extracted message was handled
                    successful, otherwise False
            """
            message = None
            try:
                message = _extract_message(update)[1]
                await asyncio.shield(self._handle(message))
            except asyncio.CancelledError:
                raise
            except:                                 # pylint:disable=bare-except
                logger.exception('error in handling message %s of update %s',
                                 repr(message), repr(update))
                return False
            else:
                return True

        hard_reset = 0
        delay = 0.
        offset = None
        while hard_reset < self.config('message_loop_retries'):
            await asyncio.sleep(hard_reset*10 + delay)
            hard_reset += 1
            delay = .2

            try:
                while True:
                    updates = await self.getUpdates(offset=offset, timeout=120)
                    logger.debug(updates)
                    self._receive_next_updates = time.time() + 120
                    for update in updates:
                        offset = update['update_id'] + 1
                        if not await _handle_update(update):
                            break

                        # valid message received and handled, exit fail-state
                        hard_reset = 0

                    await asyncio.sleep(delay)

            except (asyncio.CancelledError,
                    telepot.exception.UnauthorizedError):
                raise
            except telepot.exception.TooManyRequestsError as err:
                delay = err.json.get('parameters', {}).get('retry_after', 60.)
                logger.warning('too many requests! received a delay=%s', delay)

            except telepot.exception.BadHTTPResponse as err:
                delay = _log_http_error(delay,
                                        (err, err.status, err.text))

            except telepot.exception.TelegramError as err:
                if err.error_code == 409:
                    logger.critical(
                        'The API-KEY is in use of another service! '
                        'Telegram allows only one longpolling instance.')
                    await asyncio.sleep(120)
                    continue

                delay = _log_http_error(delay,
                                        (err, err.error_code, err.description))

            except Exception as err:              # pylint: disable=broad-except
                if 'JSON' in repr(err).upper():
                    logger.error('getUpdates received an invalid json response')
                    continue
                logger.exception('unexpected error in message loop')
            finally:
                self._receive_next_updates = 0

        logger.critical('ran out of retries, closing the message loop')
