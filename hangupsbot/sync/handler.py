"""sync handler for cross-platform messages, membership and renames"""
__author__ = 'das7pad@outlook.com'

import asyncio
import collections
import itertools
import hashlib
import logging
import random

import hangups
from hangups import hangouts_pb2

# pylint: disable=wrong-import-order
from commands import command
from exceptions import SuppressEventHandling
import handlers
import plugins
from utils.cache import Cache

from . import DEFAULT_CONFIG, SYNCPROFILE_HELP
from .exceptions import MissingArgument, UnRegisteredProfilesync
from .event import FakeEvent, SyncEvent, SyncEventMembership, SyncReply
from .image import SyncImage
from .parser import MessageSegment
from .user import SyncUser
from .sending_queue import AsyncQueueCache

logger = logging.getLogger(__name__)

# character used to generate tokens for the profile sync
TOKEN_CHAR = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

CLASSES_TO_INIT = (FakeEvent, SyncEvent, SyncEventMembership,
                   SyncImage, SyncReply)

SYNC_PLUGGABLES = ('conv_sync', 'conv_user', 'user_kick', 'profilesync',
                   'allmessages_once', 'message_once', 'membership_once')

DEFAULT_MEMORY = {
    'cache': {
        'image_upload_info': {}
    },
    'profilesync': {
        '_pending_': {}
    }
}


class SyncHandler(handlers.EventHandler):
    """router for messages and platform user request

    Args:
        bot: HangupsBot instance
        handlers_: handler.EventHandler instance, the base event handler
    """
    # forward the call to the main event handler, ignore attibute setting
    bot_command = property(lambda self: self._bot_handlers.bot_command,
                           lambda self, value: None)

    def __init__(self, bot, handlers_):
        self._bot_handlers = handlers_
        super().__init__(bot)

        # add more handler categories
        for pluggable in SYNC_PLUGGABLES:
            self.pluggables[pluggable] = []

        # set the bot class valiables
        for obj in CLASSES_TO_INIT:
            obj.bot = bot

        bot.config.set_defaults(DEFAULT_CONFIG)
        bot.memory.validate(DEFAULT_MEMORY)

        # image upload cache
        image_timeout = min(bot.config[key] for key in
                            ('sync_cache_timeout_photo',
                             'sync_cache_timeout_gif',
                             'sync_cache_timeout_video',
                             'sync_cache_timeout_sticker'))
        image_dump_intervall = bot.config['sync_cache_dump_image']
        image_dump = (image_dump_intervall, ['cache', 'image_upload_info'])
        self._cache_image = Cache(image_timeout, name='Image Upload',
                                  dump_config=image_dump)

        # conv user cache
        conv_user_timeout = bot.config['sync_cache_timeout_conv_user']
        self._cache_conv_user = Cache(conv_user_timeout, name='User Lists',
                                      increase_on_access=False)

        # sending queues
        sending_queue_timeout = bot.config['sync_cache_timeout_sending_queue']
        self._cache_sending_queue = AsyncQueueCache(
            sending_queue_timeout, 'hangouts', bot.coro_send_message)

        self.profilesync_cmds = {}
        self.profilesync_provider = {}

    ############################################################################
    # PUBLIC METHODS
    ############################################################################

    async def message(self, *, identifier, conv_id, user, text=None, reply=None,
                      title=None, edited=False, image=None, context=None,
                      previous_targets=None, notified_users=None):
        """Handle a synced message from any platform

        for all connected conversations:
            - send the message to hangouts
            - run the message through the sync handler 'allmessages'/'message'
            - if a valid G+ user is given, also pass to the bot handlers
                - 'allmessages'
                - 'message', if the user is not the bot user
                handle the message as command
            - run the message through the sync handler 'message_once' and
              'allmessages_once'

        Args:
            identifier: string, platform identifier to skip the event on receive
            conv_id: string, target Conversation ID for the message
            user: SyncUser instance of the sender
            text: string or segment list, raw message from any platform
            reply: SyncReply instance, reply wrapped in one object
            title: string, chat title of source chat
            edited: boolean, True if the message is an edited message
            image: sync.SyncImage instance, already wrapped image info
            context: dict, optional information about the message
            previous_targets: set of strings, conversation identifiers
            notified_users: set of strings, user chat ids
        """
        # pylint:disable=too-many-locals
        logger.info('received a message from %s for %s', identifier, conv_id)

        # ensure types and set targets
        image = self.get_sync_image(image=image)
        user, targets, previous_targets, notified_users = self._update_defaults(
            identifier=identifier, user=user, conv_id=conv_id,
            previous_targets=previous_targets, notified_users=notified_users)

        target_event = None

        for conv_id_ in targets:
            logger.debug('handle msg for conv %s', conv_id_)
            sync_event = SyncEvent(
                identifier=identifier, conv_id=conv_id_, user=user, text=text,
                reply=reply, title=title, edited=edited, image=image,
                notified_users=notified_users, targets=targets, context=context,
                previous_targets=previous_targets)

            # process the image and add the user_list
            await sync_event.process()

            await self._send_to_ho(sync_event, conv_id)

            if conv_id == conv_id_:
                target_event = sync_event

            logger.debug('run handler "allmessages" aka sending')
            await self._ignore_handler_suppressor(self.run_pluggable_omnibus(
                'allmessages', self.bot, sync_event, command,
                _run_concurrent_=True))

            if not sync_event.from_bot:
                await self._ignore_handler_suppressor(
                    self.run_pluggable_omnibus(
                        'message', self.bot, sync_event, command,
                        _run_concurrent_=True))

            # skip the bot._handlers if
            # they saw the event already or non G+ user raised the event
            if ('hangouts:' + conv_id_ in previous_targets
                    or user.id_.chat_id == 'sync'):
                continue

            # the message should not be relayed again
            sync_event.syncroom_no_repeat = True

            await self._ignore_handler_suppressor(
                self._bot_handlers.run_pluggable_omnibus(
                    "allmessages", self.bot, sync_event, command,
                    _run_concurrent_=True))

            if not sync_event.from_bot:
                await self._ignore_handler_suppressor(
                    self._bot_handlers.run_pluggable_omnibus(
                        "message", self.bot, sync_event, command,
                        _run_concurrent_=True))

        await self._ignore_handler_suppressor(
            self.run_pluggable_omnibus(
                'allmessages_once', self.bot, target_event, command,
                _run_concurrent_=True))

        if not sync_event.from_bot:
            await self._ignore_handler_suppressor(
                self.run_pluggable_omnibus(
                    'message_once', self.bot, target_event, command,
                    _run_concurrent_=True))

        # command not handled and a G+user (who is not the bot) raised the event
        if (not identifier.startswith('hangouts:')
                and not target_event.from_bot and user.id_.chat_id != 'sync'):
            # run the command as soon as all chats have the command-msg in queue
            await self._handle_command(target_event)

        logger.debug('done with handling')

    async def membership(self, *, identifier, conv_id, user, type_, text=None,
                         participant_user=None, title=None,
                         previous_targets=None, notified_users=None):
        """Handle a membership change from any platform

        for all connected conversations:
            - send the message to hangouts
            - run the message through the sync handler 'membership'
            - if a valid G+ user is given, also pass to the bot handler
                - 'membership'
            - run the message through the sync handler 'membership_once'

        Args:
            identifier: string, platform identifier to skip the event on receive
            conv_id: string, target Conversation ID for the message
            user: SyncUser instance of the changed user or inviter/remover
            type_: int, 1: join, 2: leave
            text: string or segment list, raw message from any platform,
                by default, this text is not used for the membership event
            title: string, chat title of source chat
            participant_user: list or users, a user could be a hangups.user.User
                like object or a string, representing a username or chat_id
            previous_targets: set of strings, conversation identifiers
            notified_users: set of strings, user chat ids

        Raises:
            AssertionError: the given membership change type is not 1 or 2
        """
        logger.info('received a membership change in %s', identifier)

        # ensure types and set targets
        user, targets, previous_targets, notified_users = self._update_defaults(
            identifier=identifier, user=user, conv_id=conv_id,
            previous_targets=previous_targets, notified_users=notified_users)

        assert type_ in (1, 2), 'the given membership change type is not 1 or 2'

        # force an update of the conv user list
        for conv_id_ in targets:
            self._cache_conv_user.pop(conv_id_, None)

        target_event = None

        for conv_id_ in targets:
            sync_event = SyncEventMembership(
                identifier=identifier, conv_id=conv_id_, user=user, text=text,
                title=title, notified_users=notified_users, type_=type_,
                participant_user=participant_user,
                targets=targets, previous_targets=previous_targets)

            # add the user_list
            await sync_event.process()

            await self._send_to_ho(sync_event, conv_id)

            if conv_id == conv_id_:
                target_event = sync_event

            await self._ignore_handler_suppressor(self.run_pluggable_omnibus(
                'membership', self.bot, sync_event, command,
                _run_concurrent_=True))

            # skip the bot._handlers if
            # they saw the event already or non G+ user raised the event
            if ('hangouts:' + conv_id_ in previous_targets
                    or user.id_.chat_id == 'sync'):
                continue

            await self._ignore_handler_suppressor(
                self._bot_handlers.run_pluggable_omnibus(
                    "membership", self.bot, sync_event, command,
                    _run_concurrent_=True))

        await self._ignore_handler_suppressor(
            self.run_pluggable_omnibus(
                'membership_once', self.bot, target_event, command,
                _run_concurrent_=True))

    async def kick(self, *, user, conv_id):
        """kick a platform user out of the synced chats

        Args:
            user: SyncUser instance
            conv_id: string, conversation identifier

        Returns:
            set, results from all platforms, expect the items None: ignored,
                False: kick failed, True: kicked, 'whitelisted'
        """
        conv_ids = self.get_synced_conversations(conv_id=conv_id,
                                                 include_source_id=True)

        raw_results = await asyncio.gather(
            *[self._gen_handler_results('user_kick', conv_id_, user)
              for conv_id_ in conv_ids])
        results = set()
        for result in raw_results:
            results.update(result.values())
        return results

    async def get_image_upload_info(self, image_data, image_filename,
                                    image_cache=None):
        """try to fetch a cached upload info or upload the image data to Google

        Args:
            image_data: io.BytesIO instance, containing the raw image_data
            image_file_name: string, including a valid image file extension
            image_cache: int, time in sec for the image info to remain in cache

        Returns:
            a hangups.client.UploadedImage instance or None if the image upload
             failed
        """
        image_raw = image_data.getvalue()
        image_hash = hashlib.md5(image_raw).hexdigest()
        cache_entry = self._cache_image.get(image_hash, ignore_timeout=True)
        if cache_entry is not None:
            logger.debug('cache hit for image=%s', image_filename)
            return hangups.client.UploadedImage(*cache_entry)

        try:
            upload_info = await self.bot.upload_image(
                image_data, image_filename, return_uploaded_image=True)

        except hangups.NetworkError as err:
            logger.info('image upload: label: %s | size: %s',
                        image_filename, len(image_raw))
            logger.warning('image upload failed: %s', repr(err))
            return None

        else:
            self._cache_image.add(image_hash, upload_info, image_cache)
            return upload_info

    def get_sync_user(self, *, identifier=None, user=None, user_id=None,
                      user_name=None, user_link=None, user_photo=None,
                      user_nick=None, user_is_self=False):
        """get a SyncUser object

        Args:
            identifier: string, source plugin name
            user: hangups.user.User instance or string as fallback
            user_id: string or hangups.user.UserID, G+ID, or platform id
            user_name: string, Fullname
            user_link: string, advaned identifier for cross platform sync
            user_photo: string, url to the user's profile picture
            user_nick: string, custom nickname
            user_is_self: boolean, simulate the bot user is certain cases

        Returns:
            sync.user.SyncUser instance
        """
        if isinstance(user, SyncUser):
            return user

        return SyncUser(self.bot, identifier=identifier, user=user,
                        user_id=user_id, user_name=user_name,
                        user_link=user_link, user_photo=user_photo,
                        user_nick=user_nick, user_is_self=user_is_self)

    @staticmethod
    def get_sync_image(*, image=None, data=None, cache=None, filename=None,
                       type_=None, size=None, url=None, cookies=None,
                       headers=None):
        """safely get a SyncImage instance

        provide one of these combinations:
        - image, standalone to validate
        - data and filename, opt: type_, size and cache
        - url, opt: auth with header and cookies, type_, filename, size, cache

        Args:
            image: sync.image.SyncImage instance
            data: file-like object, containing the raw image_data
            cache: int, time in sec for the upload info to remain in cache
            filename: string, including a valid image file extension
            type_: string, 'photo', 'sticker', 'gif', 'video'
            size: tuple of int, width and height in px
            url: string, public url of the image
            cookies: dict, custom cookies to authenticate a download
            headers: dict, custom header to authenticate a download

        Returns:
            a SyncImage or None if no valid Image could be created
        """
        if isinstance(image, SyncImage):
            return image

        if data is None and url is None:
            return None

        try:
            return SyncImage(data=data, cache=cache, filename=filename,
                             type_=type_, size=size, url=url, cookies=cookies,
                             headers=headers)
        except (MissingArgument, ValueError):
            data = len(data) if data else None
            logger.exception('unable to init a SyncImage, locals %s', locals())
            return None


    def get_synced_conversations(self, *, conv_id, return_flat=True,
                                 caller=None, unique_conv_ids=True,
                                 include_source_id=False):
        """get all conversations a message would/should reach on sending

        Args:
            conv_id: string, conversation identifier
            return_flat: boolean, change the output behaviour
            caller: string, identifier to allow recursive calls
            unique_conv_ids: boolean, filter duplicates, toggle also return_flat
            include_source_id: boolean, toggle to add the input id to the output

        Returns:
            If return_flat: list of conv_ids, otherwise a dict with keys:
            handler and values lists of conv_ids
        """
        conv_ids = self._get_handler_results('conv_sync', conv_id, caller,
                                             return_flat=False)

        if not return_flat:
            if include_source_id:
                conv_ids['_original_'] = [conv_id]
            return conv_ids

        # flat dict and get unique conv_ids
        flat_conv_ids = itertools.chain.from_iterable(conv_ids.values())

        if unique_conv_ids:
            # remove duplicates and the source id as well
            filtered = set(flat_conv_ids)
            filtered.discard(conv_id)
        else:
            filtered = flat_conv_ids

        # if requested, add the source conv_id as the first id
        return ([conv_id] if include_source_id else []) + list(filtered)

    async def get_users_in_conversation(self, conv_id, profilesync_only=False,
                                        return_flat=True, unique_users=True):
        """get all attending users of a conversation

        Args:
            conv_id: string, a unique conversation identifier
            profilesync_only: boolean, set to True to get only G+ user
            return_flat: boolean, change the output behaviour
            unique_users: boolean, filter duplicates by user_link and fullname
                only allowed if return_flat is True
        Returns:
            If return_flat: list of sync.user.SyncUser, otherwise a dict with
            keys: connected conv_ids, containing dicts with keys: handler and
            values: list of sync.SyncUser
        """
        if profilesync_only and return_flat and unique_users:
            cached_users = self._cache_conv_user.get(conv_id)
            if cached_users is not None:
                return cached_users

        conv_ids = self.get_synced_conversations(conv_id=conv_id,
                                                 include_source_id=True)

        if return_flat:
            per_handler = collections.defaultdict(list)
        else:
            per_conv = dict()

        conv_users = await asyncio.gather(
            *[self._gen_handler_results('conv_user', conv_id_, profilesync_only)
              for conv_id_ in conv_ids])

        for conv_id_ in conv_ids:
            if return_flat:
                for handler, platform_users in conv_users.pop(0).items():
                    per_handler[handler].extend(platform_users)
            else:
                per_conv[conv_id_] = conv_users.pop(0)

        if not return_flat:
            return per_conv

        flat_users = itertools.chain.from_iterable(per_handler.values())
        if not unique_users:
            return list(flat_users)
        # use a dict with keys fullname, chat_id to filter the user
        # using the userlink as key would catch platform specific links that
        #  would result in two users for a single G+ User
        filtered_users = list(
            {(user.full_name,
              user.id_.chat_id): user for user in flat_users}.values())
        if profilesync_only:
            # only cache the flat user list with G+ users and no duplicates
            self._cache_conv_user.add(conv_id, filtered_users)
        return filtered_users

    def register_handler(self, function, pluggable="message", priority=50):
        """register a handler for a single type

        Args:
            function: callable, the handling function/coro
            pluggable: string, a pluggable of .pluggables

        Raises:
            KeyError: unknown pluggable specified
            ValueError: provide pluggable does not support async functions
        """
        if (pluggable in ('conv_sync',) and
                asyncio.iscoroutinefunction(function)):
            raise ValueError('%s does not support async functions' % pluggable)

        super().register_handler(function, pluggable, priority)

    def register_profile_sync(self, platform, cmd=None, label=None):
        """add the platform to the profilesync and its cmd to the help text

        Note: to start a profilesync a command must be set for the platform

        confirmed syncs will be broadcasted to the 'profilesync' handlers:
        footprint: func(bot, platform, remote_user, conv_1on1, split_1on1s)
        the variables are passed by keyword, you may drop an argument, but the
        variable-names may not differ

        Args:
            platform: string, identifier for the platform
            platform_cmd: string, command to start the sync from the platform
            label: string, set a custom display label for this platform
        """
        path = ['profilesync', platform]
        structure = {'ho2': {}, '2ho': {},
                     'pending_2ho': {}, 'pending_ho2': {}}
        self.bot.memory.validate(structure, path)
        self.bot.memory.save()

        if not cmd:
            self.profilesync_provider[platform] = False
            return
        self.profilesync_provider[platform] = True

        label = label if isinstance(label, str) else platform
        self.profilesync_cmds[platform] = (label, cmd)

        self._update_syncprofile_help()

    def start_profile_sync(self, platform, user_id):
        """start syncing a profile for a user on the given platform

        see doc of `.register_profile_sync` for details

        Args:
            platform: string, identifier for the platform
            user_id: string, user who started the sync on the given platform

        Returns:
            string, token for the running sync
        """
        if platform not in self.profilesync_cmds:
            raise UnRegisteredProfilesync(
                ('{} is not known, perform bot.sync.register_profile_sync on'
                 'plugin init to use this method').format(platform))
        token = None
        path = ['profilesync', '_pending_']
        # get unique token
        while token is None or self.bot.memory.exists(path):
            token = ''.join(random.SystemRandom().sample(TOKEN_CHAR, 7))
            path = ['profilesync', '_pending_', token]

        self.bot.memory.set_by_path(path, platform)

        path = ['profilesync', platform]
        self.bot.memory.set_by_path(path + ['pending_2ho', user_id], token)
        self.bot.memory.set_by_path(path + ['pending_ho2', token], user_id)

        self.bot.memory.save()
        return token

    ############################################################################
    # PRIVATE METHODS
    ############################################################################

    async def setup(self, _conv_list=None):
        """async init part of the handler"""
        # create a new entry
        await plugins.tracking.start({'module': 'sync.handler',
                                      'module.path': 'sync.handler',
                                      'identifier': 'hangouts'})
        self._cache_image.start()
        self._cache_conv_user.start()
        self._cache_sending_queue.start()

        # add the handler with a very high priority
        plugins.register_handler(self._handle_message, 'message', -1000)
        plugins.register_handler(self._handle_sending, 'sending', 1000)
        plugins.register_handler(self._handle_membership, 'membership', -1000)

        self.register_handler(self._handle_conv_user, 'conv_user')
        self.register_handler(self._handle_user_kick, 'user_kick')

        # save registered items
        plugins.tracking.end()

    @staticmethod
    async def _ignore_handler_suppressor(call):
        """block event suppressing

        Args:
            call: awaitable coroutine function with arguments
        """
        try:
            await call
        except SuppressEventHandling:
            logger.exception('event suppressing blocked by SyncHandler')

    async def _handle_sending(self, bot, broadcast_targets, context):
        """forward an outgoing (non-sync) message to the message handler

        Note: messages without an image_id will be sent via the SyncHandler to
              keep the sequence of messages

        Args:
            bot: HangupsBot instance
            broadcast_targets: list of tuple, (conv_id, hangups.ChatMessage)
            context: dict, additional info about the message/conv
        """
        if context.get('syncroom_no_repeat'):
            # sync related message, already handled
            return

        messages = broadcast_targets.copy()
        targets = set('hangouts:' + message[0] for message in messages)
        for message in messages:
            conv_id, text, image_id = message
            title = bot.conversations.get_name(conv_id, '')
            if image_id is None:
                previous_targets = targets - set(('hangouts:' + conv_id,))
                # skip direct sending and add it to the message queue instead
                broadcast_targets.remove(message)
            else:
                # skip sending to the given conv
                previous_targets = targets

            user = self.get_sync_user(identifier='bot',
                                      user_id=self.bot.user_self()['chat_id'])
            await self.message(identifier='bot', conv_id=conv_id, user=user,
                               text=text, title=title, context=context,
                               previous_targets=previous_targets)

    async def _handle_message(self, dummy, event):
        """forward an incoming message from hangouts to the message handler

        Args:
            dummy: HangupsBot instance
            event: hangups Event instance
        """
        segments = MessageSegment.replace_markdown(event.conv_event.segments)
        if event.syncroom_no_repeat:
            # this is a relayed message
            return

        if event.conv_event.attachments:
            # pylint: disable=protected-access
            raw = event.conv_event._event.chat_message.message_content
            image_raw = raw.attachment[0].embed_item.plus_photo.thumbnail

            # stickers have no private url
            image_type = 'sticker' if not image_raw.url else None
            url = image_raw.url or image_raw.image_url

            size = (image_raw.width_px, image_raw.height_px)
            await asyncio.sleep((size[0] * size[1]) / 10**7)

            image = self.get_sync_image(
                url=url, filename=image_raw.image_url, type_=image_type,
                size=size,
                cookies=self.bot._client._cookies)
        else:
            image = None

        await self.message(identifier='hangouts:' + event.conv_id,
                           conv_id=event.conv_id, user=event.user, image=image,
                           title=event.conv.name,
                           text=segments)

    async def _handle_membership(self, dummy, event):
        """forward a membership change on hangouts to the membership handler

        Args:
            dummy: HangupsBot instance
            event: hangups Event instance
        """
        if isinstance(event, SyncEventMembership):
            return

        participant_ids = event.conv_event.participant_ids
        if (len(participant_ids) == 1 and
                participant_ids[0].chat_id == event.user_id.chat_id):
            participant_ids = []

        await self.membership(
            identifier='hangouts:' + event.conv_id, conv_id=event.conv_id,
            user=event.user, type_=event.conv_event.type_,
            participant_user=participant_ids, title=event.conv.name)

    @staticmethod
    async def _handle_conv_user(bot, conv_id, dummy):
        """get all hangouts user for this conv_id

        Args:
            bot: HangupsBot instance
            conv_id: string, conversation identifier
            dummy: boolean, unused

        Returns:
            list of sync.user.SyncUser
        """
        if conv_id not in bot.conversations:
            return []
        chat_ids = bot.conversations[conv_id]['participants']
        users = []
        for chat_id in chat_ids:
            users.append(SyncUser(bot, identifier='hangouts:' + conv_id,
                                  user_id=chat_id))
        return users

    async def _handle_user_kick(self, bot, conv_id, user):
        """kick a user from a given conversation

        Args:
            bot: HangupsBot instance
            conv_id: string, conversation identifier
            user: SyncUser instance

        Returns:
            None: ignored, False: kick failed, True: kicked or 'whitelisted'
        """
        if user.identifier != 'hangouts:' + conv_id:
            return None

        chat_id = user.id_.chat_id

        if (user.is_self or
                chat_id in bot.get_config_suboption(conv_id, 'admins')):
            # bot user and admins are whitelisted
            return 'whitelisted'

        if not (conv_id in bot.conversations and
                chat_id in bot.conversations[conv_id]["participants"]):
            # would result in invalid requests otherwise
            return False

        request = hangouts_pb2.RemoveUserRequest(
            request_header=self.bot.get_request_header(),
            event_request_header=hangouts_pb2.EventRequestHeader(
                conversation_id=hangouts_pb2.ConversationId(id=conv_id),
                client_generated_id=self.bot.get_client_generated_id()),
            participant_id=hangouts_pb2.ParticipantId(gaia_id=chat_id))
        try:
            await self.bot.remove_user(request)
        except hangups.NetworkError:
            logger.exception('kick %s from %s', chat_id, conv_id)
            return False
        return True

    async def _send_to_ho(self, event, original_conv_id):
        """send a message to the event conv

        Args:
            event: event.SyncEvent instance
            original_conv_id: string, original target conversation of the event
        """
        ho_tag = 'hangouts:' + event.conv_id
        if ho_tag in event.previous_targets:
            return
        event.previous_targets.add(ho_tag)

        text = event.get_formated_text(names_text_only=True)
        if text is None:
            return

        conv_id = event.conv_id
        queue = self._cache_sending_queue.get(conv_id)
        image_id = await event.get_image_id()

        # attach the context to the original conversation only
        context = event.context if event.conv_id == original_conv_id else {}

        if not context:
            # do not store the context if nothing was added so far
            context['__ignore__'] = True
        context['syncroom_no_repeat'] = True
        queue.schedule(conv_id, text, image_id=image_id, context=context)

    def _update_defaults(self, *, identifier, user, conv_id, previous_targets,
                         notified_users):
        """set defaults and ensure types

        Args:
            identifier: string, platform identifier to skip the event on receive
            conv_id: string, target Conversation ID for the message
            user: SyncUser instance of the sender
            previous_targets: set of strings, conversation identifiers
            notified_users: set of strings, user chat ids

        Returns:
            tuple: user, targets, previous_targets, notified_users
        """
        user = self.get_sync_user(identifier=identifier, user=user)

        targets = self.get_synced_conversations(conv_id=conv_id,
                                                include_source_id=True)

        previous_targets = (previous_targets
                            if isinstance(previous_targets, set)
                            else set((identifier,)))

        notified_users = (notified_users if isinstance(notified_users, set)
                          else set((user.id_.chat_id,)))

        return user, targets, previous_targets, notified_users

    async def _gen_handler_results(self, pluggable, *args, return_flat=False):
        """async get the results of each handler of the given pluggable

        Args:
            pluggable: string, key in .pluggables
            return_flat: boolean, get the results as one iterable

        Returns:
            if return_flat is True:
                a dict, plugins names as key, values are the results
            otherwise: tuple with all results
        """
        async def _run(handler):
            """run a handler with provided arguments and log any exception

            Args:
                handler: coroutine function

            Raises:
                AssertionError: any exception was raised inside the handler
            """
            try:
                result = handler(self.bot, *args)
                if asyncio.iscoroutinefunction(handler):
                    return await result
                return result
            except:                                # pylint: disable=bare-except
                logger.exception('%s: %s with args=%s',
                                 pluggable, handler.__name__,
                                 str([str(arg) for arg in args]))
                raise AssertionError()

        handlers_ = self.pluggables[pluggable].copy()
        results_unmapped = await asyncio.gather(*[_run(handler[0])
                                                  for handler in handlers_],
                                                return_exceptions=True)

        results = {}
        for handler in handlers_:
            meta_data = handler[2]
            key = meta_data.get('identifier') or meta_data.get('module.path')
            results[key] = results_unmapped.pop(0)
            if isinstance(results[key], Exception):
                results.pop(key)

        if return_flat is True:
            return tuple(itertools.chain.from_iterable(results.values()))
        return results

    def _get_handler_results(self, pluggable, *args, return_flat=False):
        """get the results of each registered handler for the given pluggable

        Args:
            pluggable: string, key in .pluggables
            return_flat: boolean, get the results as one iterable

        Returns:
            if return_flat is True:
                a dict, plugins names as key, values are the results
            otherwise: tuple with all results
        """
        def _run(handler):
            """run a handler with provided arguments and log any exception

            Args:
                handler: coroutine function

            Raises:
                AssertionError: any exception was raised inside the handler
            """
            try:
                return handler(self.bot, *args)
            except:                                # pylint: disable=bare-except
                logger.exception('%s: %s with args=%s',
                                 pluggable, handler.__name__,
                                 str([str(arg) for arg in args]))
                raise AssertionError()

        results = {}
        for handler in self.pluggables[pluggable].copy():
            function, meta = handler[0:3:2]
            key = meta.get('identifier') or meta.get('module.path')
            try:
                results[key] = _run(function)
            except AssertionError:
                pass
        if return_flat is True:
            return tuple(itertools.chain.from_iterable(results.values()))
        return results

    def _update_syncprofile_help(self):
        """insert the profilesync commands per platform into the command help"""
        cmds = []
        for label_, cmd_ in self.profilesync_cmds.values():
            cmds.append('<b>{}</b>: {}'.format(label_, cmd_))

        plugins.register_help(
            SYNCPROFILE_HELP.format(bot_cmd='{bot_cmd}',
                                    platform_cmds='\n'.join(cmds)),
            name='syncprofile')
