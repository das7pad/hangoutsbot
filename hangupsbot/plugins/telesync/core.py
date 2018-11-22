"""Telepot sync-bot"""
__author__ = 'das7pad@outlook.com'

import asyncio
import io
import json
import logging
import random
import time

import aiohttp
import telepot
import telepot.aio
import telepot.aio.api
import telepot.exception
from telepot.loop import _extract_message

from hangupsbot import plugins
from hangupsbot.base_models import BotMixin
from hangupsbot.sync.parser import get_formatted
from hangupsbot.sync.sending_queue import AsyncQueueCache
from .commands_tg import (
    RESTRICT_OPTIONS,
    command_add_admin,
    command_cancel,
    command_chattitle,
    command_clear_sync_ho,
    command_echo,
    command_get_admins,
    command_get_me,
    command_leave,
    command_remove_admin,
    command_restrict_user,
    command_set_sync_ho,
    command_set_sync_profile,
    command_start,
    command_sync_config,
    command_sync_profile,
    command_tldr,
    command_unsync_profile,
    command_whereami,
    command_whoami,
    command_whois,
    restrict_users,
)
from .exceptions import IgnoreMessage
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
    'migrate_from_chat_id',  # duplicate of 'migrate_to_chat_id'
)
LEFT_CHAT_MEMBER_STATUS = (
    'left',
    'kicked',
)

telepot.aio.api._timeout = 15  # pylint: disable=protected-access
PERMANENT_SERVER_ERROR = telepot.exception.TelegramError(
    'Request failed permanent',
    500,
    {}
)

_RESTRICT_USERS_FAILED = _('<b>WARNING</b>: Rights for {names} in TG '
                           '<i>{chat_name}</i> could <b>not</b> be restricted, '
                           'please check manually!')


class TelegramBot(telepot.aio.Bot, BotMixin):
    """enhanced telepot bot with Hangouts sync

    Args:
        ho_bot (hangupsbot.core.HangupsBot): the running instance
    """

    def __init__(self, ho_bot):
        Message.tg_bot = self
        self.user = None

        api_key = self.config('api_key', False)
        super().__init__(api_key)

        self._cache_sending_queue = AsyncQueueCache('telesync', self._send_html,
                                                    bot=ho_bot)
        self._cache_sending_queue.start()

        self._commands = {
            '/whoami': command_whoami,
            '/whereami': command_whereami,
            '/whois': command_whois,
            '/setsyncho': command_set_sync_ho,
            '/clearsyncho': command_clear_sync_ho,
            '/addadmin': command_add_admin,
            '/removeadmin': command_remove_admin,
            '/syncprofile': command_sync_profile,
            '/setsyncprofile': command_set_sync_profile,
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

    @staticmethod
    def _get_error_message(error, code, reason):
        """get a custom error message for an error

        telepot.exception.BadHTTPResponse and telepot.exception.TelegramError
         have a different API. This demands the two additional arguments.

        Args:
            error (Exception): the full error
            code (int): the resp status code
            reason (str): the error message

        Returns:
            str: a status message
        """
        if code >= 500:
            flat = repr(error).lower()
            if 'restart' in flat or 'gateway' in flat:
                reason = 'pending server restart'
            message = 'Telegram server error'
        elif code:
            message = 'Unexpected response'
        else:
            message = 'Unexpected error'
        return '%s (%s)' % (message, reason)

    async def _api_request(self, method, params=None, files=None, **kwargs):
        retry = 0
        limit = 1  # ensure at least one try
        last_err = None
        tracker = object()  # tracker for log entries
        logger.debug(
            'api request %s: method %r, params %s, file %r, kwargs %r',
            id(tracker), method, params, files, kwargs,
        )

        while retry <= limit:
            delay = 0
            try:
                return await super()._api_request(
                    method=method,
                    params=params,
                    files=files,
                    **kwargs
                )
            except telepot.exception.TooManyRequestsError:
                msg = 'too many requests!'
                delay = 30

            except telepot.exception.BadHTTPResponse as err:
                msg = self._get_error_message(err, err.status, err.text)

            except telepot.exception.TelegramError as err:
                if err.error_code < 500:
                    raise

                msg = self._get_error_message(err, err.error_code,
                                              err.description)

            last_err = msg
            retry += 1
            limit = self.config('request_retry_limit')
            if retry == 1 and not logger.isEnabledFor(logging.DEBUG):
                logger.info(
                    'api request %s: method %r, params %s, file %r, kwargs %r',
                    id(tracker), method, params, files, kwargs,
                )
            logger.info(
                'api request %s: %s/%s failed: %r',
                id(tracker), retry, limit, msg
            )
            await asyncio.sleep(delay or max(2 ** retry, 30))

        logger.error(
            'api request %s: failed %s times. Last error: %r',
            id(tracker), limit, last_err
        )
        raise PERMANENT_SERVER_ERROR

    def config(self, key=None, fallback=True):
        """get a telegram config entry

        Args:
            key (str): an item in the telesync config
            fallback (bool): toggle to use the config defaults on missing keys

        Returns:
            mixed: the requested item; dict, entire config if no key is set
        """
        item = [key] if key is not None else []
        return self.bot.config.get_by_path(['telesync'] + item, fallback)

    async def start(self):
        """init the bot user and commands, start the reminder and MessageLoop"""
        bot_user = await self.getMe()
        bot_chat_id = self.bot.user_self()['chat_id']
        self.bot.memory.set_defaults(
            {bot_user['id']: bot_chat_id},
            path=['profilesync', 'telesync', '2ho'])

        self.user = User(self, {'bot': bot_user, 'chat': {'id': None}},
                         chat_action='bot')
        logger.info('Bot user: id: %s, name: %s, username: %s',
                    self.user.usr_id, self.user.first_name, self.user.username)

        tasks = [
            asyncio.ensure_future(self._periodic_membership_checker()),
            asyncio.ensure_future(self._periodic_profile_updater()),
            asyncio.ensure_future(self._periodic_profilesync_reminder()),
        ]

        try:
            await self._message_loop()
        except asyncio.CancelledError:
            return
        except telepot.exception.UnauthorizedError:
            logger.warning('API-Key revoked!')
        finally:
            await self._cache_sending_queue.stop(timeout=5)

            # cancel housekeeping tasks
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            try:
                # discard the last few messages
                # TODO(das7pad): move the update discarding into the message loop
                old_messages = [item['update_id']
                                for item in await self.getUpdates(offset=-1)]
                if old_messages:
                    logger.info('discard the updates %s', old_messages)
                    await self.getUpdates(offset=max(old_messages) + 1)
            except telepot.exception.TelegramError as err:
                logger.error('discard of last messages failed: %r', err)

    async def can_log_in(self, retry=True):
        """check whether Telegram api requests can be made

        Args:
            retry (bool): toggle to allow a single retry on a Server Error

        Returns:
            bool: True if the TelegramBot is running, otherwise False
        """
        try:
            await self.getMe()
        except telepot.exception.UnauthorizedError:
            logger.warning('API-KEY is not valid, unloading the plugin')
            asyncio.ensure_future(plugins.unload(self.bot, 'plugins.telesync'))
            retry = False
        except (telepot.exception.TelegramError, aiohttp.ClientError) as err:
            logger.error('API check: %r', err)
        else:
            return True

        if retry:
            logger.warning('not running, reloading the plugin')
            # detach the execution as the current call may be cancelled soon
            asyncio.ensure_future(
                plugins.reload_plugin(self.bot, 'plugins.telesync'))
        return False

    def send_html(self, tg_chat_id, html):
        """send html to telegram chat keeping the sequence

        Args:
            tg_chat_id (mixed): a chat the bot user has access to
            html (str): nested html tags are not allowed

        Returns:
            sync.sending_queue.Status: status of the scheduled task which
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
            user_id (str): user identifier
            chat_id (str): telegram chat identifier
            gpluslink (bool): set to True get G+Links instead of t.me links
            use_cache (bool): set to False to ignore a cache hit and to
             perform an API request for updated user data

        Returns:
            User: a subclass of sync.user.SyncUser
        """
        path_user = ['telesync', 'user_data', user_id]

        if self.bot.memory.exists(path_user):
            tg_user = self.bot.memory.get_by_path(path_user)
        else:
            tg_user = None

        if not (use_cache and tg_user is not None):
            if chat_id is not None:
                logger.debug('fetch user %s in %s', user_id, chat_id)
                remove_user = ''
                try:
                    response = await self.getChatMember(chat_id, user_id)
                except telepot.exception.TelegramError as err:
                    if user_id != chat_id:
                        # the user is likely a former member, remove him
                        remove_user = 'exception: %s' % (
                            err.description
                        )
                else:
                    tg_user = response.get('user')

                    if response.get('status') in LEFT_CHAT_MEMBER_STATUS:
                        remove_user = 'status: %s' % response.get('status')

                if remove_user:
                    logger.info(
                        'memory cleanup %s: '
                        'remove user %s from chat %s with reason %r',
                        id(tg_user), user_id, chat_id, remove_user
                    )
                    try:
                        self.bot.memory.pop_by_path(
                            ['telesync', 'chat_data', str(chat_id),
                             'user', str(user_id)])
                    except KeyError as err:
                        logger.error(
                            'memory cleanup %s: '
                            'remove user from chat with reason %r: %r',
                            id(tg_user), remove_user, err
                        )
                        chat_id = None

            if tg_user is None:
                tg_user = {'id': user_id, 'first_name': 'unknown'}
        user = User(self, {'user': tg_user, 'chat': {'id': chat_id}},
                    chat_action='user', gpluslink=gpluslink)
        await user.update_user_picture(use_cache=use_cache)
        return user

    async def get_image(self, image, type_='photo', extension=None):
        """download an image from Telegram and create a data wrapper for it

        Args:
            image (dict): media item from telegram
            type_ (str): 'photo', 'sticker', 'gif', 'video'
            extension (str): opt, file extension

        Returns:
            hangupsbot.sync.image.SyncImage: the image or None in case no image
                could be created
        """
        image_data = io.BytesIO()
        logger.info(
            'download media %s: request %r, media type %r',
            id(image_data), image, type_
        )
        try:
            await self.download_file(image['file_id'], image_data)
        except telepot.exception.TelegramError as err:
            logger.error(
                'download media %s: failed with %r',
                id(image_data), err
            )
            image_data.close()
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

        if extension != 'mp4' or type_ == 'video':
            return image

        logger.info('download media %s: post process gif', id(image_data))

        # telegram converts gifs to videos, we have to do that in reverse
        await image.process()

        image._data, image._filename = image.get_data(video_as_gif=True)
        return image

    async def profilesync_info(self, user_id, is_reminder=False):
        """send info about pending profilesync to user

        Args:
            user_id (str): identifier for the user and its 1on1 chat with the bot
            is_reminder (bool): set to True to prepend the reminder flag
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
            tg_chat_id (int): a chat the bot user has access to
            text (str): nested html tags are not allowed
            silent (bool): set to True to disable a client notification

        Returns:
            bool: True in case of a successful api-call, otherwise False
        """
        if not text:
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

        except telepot.exception.TelegramError as err:
            status = False
            logger.info(
                'sending html %s: chat %r, content %r',
                id(text), tg_chat_id, text
            )
            if ('chat not found' in err.description
                    or 'bot was blocked by the user' in err.description):
                logger.warning(
                    'sending html %s: %r',
                    id(text), err.description
                )
                next_part = None
            elif 'can\'t parse entities in message text' in err.description:
                logger.error(
                    'sending html %s: content has bad html',
                    id(text)
                )
                status = await self._send_html(tg_chat_id,
                                               get_formatted(text, 'text'),
                                               as_html=False, silent=silent)
            else:
                logger.error(
                    'sending html %s: failed with %r',
                    id(text), err
                )

        else:
            Message.add_message(self.bot, int(tg_chat_id), msg.get('message_id'))
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
            msg (message.Message): a message wrapper

        Returns:
            tuple[bool, str, list[str]]: cmd is valid, command, arguments
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
            response (dict): api-response from telepot
        """
        logger.debug('message %s: %r', id(response), response)
        if 'migrate_to_chat_id' in response:
            self._on_supergroup_upgrade(response)
            return

        if (telepot.flavor(response) != 'chat'
                or any(key in response for key in IGNORED_MESSAGE_TYPES)):
            return

        try:
            msg = Message(response)
        except IgnoreMessage:
            logger.debug('message %s: ignore message', id(response))
            return

        if msg.content_type == 'text':
            valid, cmd, params = self._parse_command(msg)
            if valid and not await self._commands[cmd](self, msg, *params):
                # the command is valid and the command shall not be synced
                return

        if msg.content_type in ('new_chat_member', 'new_chat_members',
                                'left_chat_member'):
            await self._on_membership_change(msg)

        else:
            await self._forward_content(msg)

    async def _forward_content(self, msg):
        """message handler for text, photo, sticker, location

        Args:
            msg (message.Message): a message wrapper
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

        segments = TelegramMessageSegment.from_text_and_entities(
            msg.text, msg.get('entities', []))

        for conv_id in ho_conv_ids:
            asyncio.ensure_future(self.bot.sync.message(
                identifier='telesync:' + msg.chat_id, conv_id=conv_id,
                user=msg.user, text=segments,
                reply=await msg.get_reply(), image=image,
                title=msg.get_group_name(), edited=msg.edited))

    async def _on_membership_change(self, msg):
        """forward a membership change

        Args:
            msg (message.Message): a message wrapper
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

        type_ = 2
        for changed_member in changed_members:
            path_chat = ['telesync', 'chat_data', msg.chat_id, 'user',
                         changed_member.usr_id]
            if msg.content_type == 'left_chat_member':
                type_ = 2
                if bot.memory.exists(path_chat):
                    bot.memory.pop_by_path(path_chat)
            else:
                bot.memory.set_by_path(path_chat, 1)
                type_ = 1

        bot.memory.save()

        if type_ == 1:
            await self._restrict_new_user(msg, changed_members)

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

    async def _restrict_new_user(self, msg, changed_members):
        """restrict new members in supergroups as configured

        Args:
            msg (Message): a membership change message
            changed_members (list[telesync.user.User]): the members to restrict
        """
        if msg.chat_type != 'supergroup':
            return
        mod_chat = self.config('mod_chat')
        chat_name = msg.get_group_name()
        mode = self.bot.get_config_suboption('telesync:' + msg.chat_id,
                                             'restrict_users')

        logger.info(
            'restricting new users %s: chat %r, restrict mode %r, users %r',
            id(changed_members), msg.chat_id, mode, changed_members
        )

        if mode in RESTRICT_OPTIONS:
            failed = await restrict_users(
                self, msg.chat_id, mode,
                (user.usr_id for user in changed_members),
                silent=True)
            if failed:
                failed_names = ', '.join(
                    '%s (%s)' % (user.full_name, user.usr_id)
                    for user in changed_members)
                if mod_chat:
                    self.send_html(
                        mod_chat,
                        _RESTRICT_USERS_FAILED.format(names=failed_names,
                                                      chat_name=chat_name))

                logger.info(
                    'restricting new users %s: failed for users %r',
                    id(changed_members), failed
                )
                logger.error(
                    'restricting new users %s: failed with %r',
                    id(changed_members), failed.values()
                )
        elif mode:
            logger.warning(
                'restricting new users %s: %r is an invalid restrict mode, '
                'check conversation or global config for "restrict_users"',
                id(changed_members), mode
            )
            if mod_chat:
                message = _(
                    'Check the config value `restrict_users` for the chat '
                    '{name} ({chat_id}), expected one of {valid_values}'
                ).format(name=chat_name, chat_id=msg.chat_id,
                         valid_values=', '.join(RESTRICT_OPTIONS))
                self.send_html(mod_chat, '<b>ERROR</b>: %s' % message)

    def _on_supergroup_upgrade(self, msg):
        """migrate all old data to a new chat id

        Args:
            msg (dict): message from Telegram
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
        except Exception:  # pylint: disable=broad-except
            logger.exception('low level error in periodic profilesync reminder')

    async def _periodic_profile_updater(self):
        """update the telesync data periodically

        sleep for x hours after each update run
        x determined by telesync config entry 'profile_update_interval'

        this could likely end in a rate limit, delay each query by 10-20 seconds
        """
        memory = self.bot.memory

        async def update_user(chat_id, user_id):
            last_update_path = ['telesync', 'user_data', user_id, 'last_update']
            if (memory.exists(last_update_path)
                    and memory.get_by_path(last_update_path) == timestamp):
                return False

            member_path = ['telesync', 'chat_data', chat_id, 'user', user_id]
            if not memory.exists(member_path):
                return False

            memory.set_by_path(last_update_path, timestamp)
            logger.debug(
                'profile update %s: user %s | chat %s',
                timestamp, user_id, chat_id
            )
            await self.get_tg_user(user_id=user_id, chat_id=chat_id,
                                   use_cache=False)
            return True

        try:
            while True:
                timestamp = int(time.time())
                chat_data = memory.get_by_path(['telesync', 'chat_data']).copy()

                logger.debug(
                    'profile update %s: started',
                    timestamp
                )
                for chat_id, data in chat_data.items():
                    for user_id in tuple(data.get('user', ())):
                        if await update_user(chat_id, user_id):
                            await asyncio.sleep(random.randint(10, 20))
                logger.debug(
                    'profile update %s: finished',
                    timestamp
                )

                memory.save()
                await asyncio.sleep(
                    3600 * self.config('profile_update_interval'))
        except asyncio.CancelledError:
            return
        except Exception:  # pylint: disable=broad-except
            logger.exception('low level error in profile updater')

    async def _periodic_membership_checker(self):
        """verify the membership list per chat periodically

        sleep for x hours after checking all conversations
        x is determined by telesync config entry 'membership_check_interval'

        in addition to the interval, this feature must be enabled in the config:
          - globally:
            "telesync"->"enable_membership_check" = 1
          - or per chat:
            for example for the chat with id 123:
            "conversations"->"telesync:123"->"enable_membership_check" = 1

        this could likely end in a rate limit, delay each query by 10-20 seconds
        """
        chat_path = ['telesync', 'chat_data']
        try:
            while True:
                chat_data = self.bot.memory.get_by_path(chat_path)
                for chat_id, data in chat_data.copy().items():
                    config_path = ['conversations', 'telesync:%s' % chat_id,
                                   'enable_membership_check']
                    if self.bot.memory.exists(config_path):
                        enabled = self.bot.memory.get_by_path(config_path)
                    else:
                        enabled = self.config('enable_membership_check')

                    if not enabled:
                        continue

                    for user_id in tuple(data.get('user', ())):
                        local_path = chat_path + [chat_id, 'user', user_id]
                        if not self.bot.memory.exists(local_path):
                            # the user left the chat
                            continue

                        await self.get_tg_user(user_id=user_id,
                                               chat_id=chat_id,
                                               use_cache=False)
                        await asyncio.sleep(random.randint(10, 20))

                self.bot.memory.save()
                await asyncio.sleep(
                    3600 * self.config('membership_check_interval'))
        except asyncio.CancelledError:
            return
        except Exception:  # pylint: disable=broad-except
            logger.exception('low level error in membership checker')

    async def _message_loop(self):
        """long polling for updates and handle errors gracefully

        Raises:
            UnauthorizedError: API-token invalid
            CancelledError: plugin unload in progress
        """

        def _reset_error_count():
            """reset the current error counter of the message loop"""
            nonlocal hard_reset
            hard_reset = 0

        async def _handle_update(update):
            """extract and handle a message of an `Update`

            Args:
                update (dict): see `https://core.telegram.org/bots/api#update`

            Raises:
                CancelledError: plugin unload in progress
            """
            message = None
            try:
                message = _extract_message(update)[1]
                await asyncio.shield(self._handle(message))
            except asyncio.CancelledError:
                logger.info(
                    'handle update %s: update %r, message [%s] %r',
                    id(update), update, id(message), message
                )
                logger.warning(
                    'handle update %s: message loop stopped, finishing the '
                    'handling of the current update in the background',
                    id(update)
                )
                raise
            except Exception:  # pylint:disable=broad-except
                logger.info(
                    'handle update %s: update %r, message [%s] %r',
                    id(update), update, id(message), message
                )
                logger.exception(
                    'handle update %s: error in handling message',
                    id(update)
                )
            else:
                # valid message received and handled, exit fail-state
                _reset_error_count()

        hard_reset = 0
        delay = 0.
        offset = None
        while hard_reset < self.config('message_loop_retries'):
            await asyncio.sleep(hard_reset * 10 + delay)
            hard_reset += 1

            try:
                while True:
                    updates = await self.getUpdates(offset=offset, timeout=120)
                    logger.debug('incoming updates: %r', updates)
                    delay = .2
                    for update_ in updates:
                        offset = update_['update_id'] + 1
                        await _handle_update(update_)

                    await asyncio.sleep(delay)

            except telepot.exception.TelegramError as err:
                if err.error_code == 409:
                    logger.warning(
                        'The API-KEY is in use of another service! '
                        'Telegram allows only one longpolling instance.')
                    delay += 120
                    await asyncio.sleep(delay)
                    continue

        logger.critical('ran out of retries, closing the message loop')
