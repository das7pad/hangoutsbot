"""core to handle message syncing and handle base requests from commands"""

import asyncio
import logging

import aiohttp

import plugins

from sync.sending_queue import AsyncQueueCache
from sync.user import SyncUser
from sync.utils import get_sync_config_entry

from .commands_slack import slack_command_handler
from .exceptions import (
    AlreadySyncingError,
    NotSyncingError,
    IgnoreMessage,
    ParseError,
    IncompleteLoginError,
    WebsocketFailed,
    SlackAPIError,
    SlackRateLimited,
    SlackAuthError,
    SlackConfigError,
)
from .message import SlackMessage
from .parsers import (
    SLACK_STYLE,
)
from .storage import (
    migrate_on_domain_change,
)


logger = logging.getLogger(__name__)

_RENAME_TEMPLATE = _('_<https://plus.google.com/{chat_id}|{name}> has renamed '
                     'the Hangout to *{new_name}*_')

# Slack RTM event (sub-)types
_CACHE_UPDATE_USERS = ('team_join', 'user_change')
_CACHE_UPDATE_GROUPS = ('group_join', 'group_leave', 'group_close',
                        'group_open', 'group_rename', 'group_name',
                        'group_archive', 'group_unarchive')
_CACHE_UPDATE_GROUPS_HIDDEN = ('group_close', 'group_open',
                               'group_rename', 'group_name',
                               'group_archive', 'group_unarchive')
_CACHE_UPDATE_CHANNELS = ('channel_join', 'channel_leave',
                          'channel_created', 'channel_deleted',
                          'channel_rename', 'channel_archive',
                          'channel_unarchive', 'member_joined_channel')
_CACHE_UPDATE_CHANNELS_HIDDEN = ('channel_created', 'channel_deleted',
                                 'channel_rename', 'channel_archive',
                                 'channel_unarchive', 'member_joined_channel')
_SYSTEM_MESSAGES = ('hello', 'pong', 'reconnect_url', 'goodbye',
                    'bot_added', 'bot_changed', 'dnd_updated_user',
                    'emoji_changed', 'desktop_notification',
                    'presence_change', 'user_typing')
_CACHE_UPDATE_TEAM = ('team_rename', 'team_domain_changed')


class SlackRTM(object):
    """hander for a single slack team

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        sink_config (dict): basic configuration including the api `key`, a
            `name` for the team and `admins` a list of slack user ids

    Raises:
        SlackConfigError: could not find the api-`key` in `sink_config`
    """
    _session = None
    logger = logger

    # tracker for concurrent api_calls, unique per instance
    _tracker = 0

    def __init__(self, bot, sink_config):
        if  not isinstance(sink_config, dict) or 'key' not in sink_config:
            raise SlackConfigError('API-`key` is missing in config %s'
                                   % repr(sink_config))
        self.bot = bot
        self.apikey = sink_config['key']
        self.slack_domain = sink_config.get('domain')
        self.conversations = {}
        self.users = {}
        self.my_uid = ''
        self.my_bid = None
        self.identifier = None
        self.name = None
        self.team = {}
        self.command_prefixes = tuple()
        self._session = aiohttp.ClientSession()
        self._cache_sending_queue = None

    @property
    def config(self):
        """get the live-config from the bot-config to allow manual changes

        Returns:
            dict: sink config

        Raises:
            SlackConfigError: could not find the sink config or `key` is missing
        """
        for config in self.bot.config.get_option('slackrtm'):
            if config.get('key') == self.apikey:
                return config

        for config in self.bot.config.get_option('slackrtm'):
            if config.get('domain') != self.slack_domain:
                continue

            if 'key' in config:
                # api-key change
                self.apikey = config['key']
                asyncio.ensure_future(self.rebuild_base())
                return config
            raise SlackConfigError('API-`key` is missing in config %s' % config)
        raise SlackConfigError('The config for team "%s" got deleted'
                               % self.slack_domain)

    @property
    def admins(self):
        """get the configured admins

        Returns:
            list: a list of slack user ids (str)
        """
        return self.config.get('admins', [])

    @property
    def syncs(self):
        """access the memory entry with configured syncs of the current team

        Returns:
            list: a list of dicts, each has two keys `hangoutid`, `channelid`
        """
        return self.bot.memory.get_by_path(
            ['slackrtm', self.slack_domain, 'synced_conversations'])

    async def start(self):
        """login, build the cache, register handler and start event polling"""
        async def _login():
            """connect to the slack api and fetch the base data

            Returns:
                dict: `team`: team data, `self`: bot user, `url`: websocket-url

            Raises:
                IncompleteLoginError:
                    connection error
                    or incomplete api-response received from `rtm.connect`
                SlackAuthError:
                    the auth-token got revoked
            """
            try:
                login_data = await self.api_call('rtm.connect')
            except SlackAPIError:
                raise IncompleteLoginError() from None

            if any(key not in login_data for key in ('self', 'team', 'url')):
                raise IncompleteLoginError()
            self.logger = logging.getLogger('plugins.slackrtm.%s'
                                            % login_data['team']['domain'])
            return login_data

        async def _build_cache(login_data):
            """set the team; fetch users, channels and groups

            Args:
                login_data (dict): slack-api response of `rtm.connect`, which
                    contains the team data in the entry `team`
            """
            self.team = login_data['team']
            await asyncio.gather(*(self.update_cache(name) for name in
                                   ('users', 'channels', 'groups', 'ims')))

        async def _set_selfuser_and_ids(login_data):
            """set the bot user and bot id to filter messages

            .rebuild_base() requires the self user being present

            Args:
                login_data (dict): slack-api response of `rtm.connect`, which
                    contains the bot user object in the entry `self`

            Raises:
                SlackAuthError: the auth-token got revoked
            """
            self.my_uid = login_data['self']['id']
            self.users[self.my_uid] = login_data['self']

            # send a message as a different user in the own dm to capture the
            # used bot id
            for retry in range(5):
                try:
                    response = await self.api_call(
                        'chat.postMessage',
                        channel=await self.get_slack1on1(self.my_uid),
                        text='~', username='~')
                    self.my_bid = response['message']['bot_id']
                except (SlackAPIError, KeyError) as err:
                    self.logger.error(
                        'Failed fetch the own `bot_id` [retry %s/5]: %s',
                        retry, repr(err))
                else:
                    return

            # NOTE: bot_messages are not handled further the `SlackMessage` in
            # general - the user may add custom message parsing to enable
            # forwarding. A bad parsing could result in duplicates.
            self.logger.critical('Could not fetch the own `bot_id` used to '
                                 'filter messages. The instance can not work '
                                 'efficient now or may send duplicates.')


        hard_reset = 0
        while hard_reset < 5:
            self.bot.config.on_reload.add_observer(self.rebuild_base)
            try:
                await asyncio.sleep(hard_reset*10)
                hard_reset += 1

                login_data = await _login()

                await _build_cache(login_data)
                await _set_selfuser_and_ids(login_data)
                await self.rebuild_base()

                await self._process_websocket(login_data['url'])
            except asyncio.CancelledError:
                return
            except IncompleteLoginError:
                self.logger.error('Incomplete Login, restarting')
            except WebsocketFailed:
                self.logger.warning('Connection failed, waiting %s sec',
                                    hard_reset * 10)
            except SlackAuthError as err:
                self._session.close()           # do not allow further api-calls
                self.logger.critical('closing SlackRTM: %s', repr(err))
                return
            except:                                 # pylint:disable=bare-except
                self.logger.exception('core error')
            else:
                self.logger.info('websocket closed gracefully, restarting')
                hard_reset = 0
            finally:
                self.logger.debug('unloading')
                self.bot.config.on_reload.remove_observer(self.rebuild_base)
                if self._cache_sending_queue is not None:
                    await self._cache_sending_queue.stop(5)
                try:
                    # cleanup
                    await plugins.unload(self.bot, self.identifier)
                except plugins.NotLoaded:
                    pass

        self.logger.critical('ran out of retries, closing the connection')

    async def rebuild_base(self):
        """reset everything that is based on the sink config or team data"""
        async def _send_message(**kwargs):
            """send the content to slack

            Args:
                kwargs (dict): see api documentation for `chat.postMessage`

            Returns:
                boolean: True in case of a successful api-call, otherwise False

            Raises:
                SlackAuthError: the api-token got revoked
            """
            self.logger.debug('sending into channel %s: %s',
                              kwargs['channel'], kwargs['text'])
            try:
                await self.api_call('chat.postMessage', **kwargs)
            except SlackAPIError:
                # already logged
                return False
            else:
                return True

        async def _register_handler():
            """register the profilesync and the sync handler"""
            label = 'Slack (%s)' % self.config.get('name', self.team['name'])
            await plugins.tracking.start({'module.path': self.identifier,
                                          'identifier': label})

            self.bot.sync.register_profile_sync(
                self.identifier,
                cmd='@%s syncprofile' % self.get_username(self.my_uid,
                                                          self.my_uid),
                label=label)

            plugins.register_handler(self._handle_ho_rename, 'rename')

            sync_handler = (
                (self._handle_profilesync, 'profilesync'),
                (self._handle_sync_message, 'allmessages'),
                (self._handle_sync_membership, 'membership'),
            )
            for handler, name in sync_handler:
                plugins.register_sync_handler(handler, name)

            self._cache_sending_queue.start()

            # save registered items
            plugins.tracking.end()

        # cleanup
        if self._cache_sending_queue is not None:
            # finish all tasks before updating the identifier
            await self._cache_sending_queue.stop(5)
        try:
            await plugins.unload(self.bot, self.identifier)
        except plugins.NotLoaded:
            pass

        # cache the config
        config = self.config

        bot_username = self.get_username(self.my_uid)
        old_domain = self.slack_domain
        self.slack_domain = config['domain'] = self.team['domain']

        if 'name' in config:
            self.name = config['name']
        else:
            self.name = '%s@%s' % (bot_username, self.slack_domain)
            logger.warning('no name set in config file, using computed name %s',
                           self.name)

        self.command_prefixes = (config['command_prefixes']
                                 if 'command_prefixes' in config else
                                 ('@hobot', '@%s' % bot_username))

        self.identifier = 'slackrtm:%s' % self.slack_domain
        self.logger = logging.getLogger('plugins.slackrtm.%s'
                                        % self.slack_domain)

        migrate_on_domain_change(self, old_domain)

        self._cache_sending_queue = AsyncQueueCache(
            self.identifier, _send_message, bot=self.bot)

        await _register_handler()

        for admin in self.admins:
            if admin not in self.users:
                self.logger.warning('admin userid %s not found in user list',
                                    admin)
        if not self.admins:
            self.logger.warning('no admins specified in config file')

    async def api_call(self, method, **kwargs):
        """perform an api call to slack

        more documentation on the api call: https://api.slack.com/web
        more documentation on methods: https://api.slack.com/methods

        delay the execution in case of a ratelimit

        Args:
            method (str): the api-method to call
            kwargs (dict): optional kwargs passed with api-method

        Returns:
            dict: pre-parsed json response

        Raises:
            SlackAPIError: invalid request
            SlackAuthError: the token got revoked
        """
        tracker = self._tracker
        self._tracker += 1
        self.logger.debug('api_call %s: (%s, %s)',
                          tracker, repr(method), repr(kwargs))
        if 'delay' in kwargs:
            delay = kwargs.pop('delay')
            self.logger.debug('api_call %s: delayed by %ss', tracker, delay)
            await asyncio.sleep(delay)
        parsed = None
        try:
            async with await asyncio.shield(self._session.post(
                'https://slack.com/api/' + method,
                data={'token': self.apikey, **kwargs})) as resp:

                parsed = await resp.json()
                self.logger.debug('api_call %s: %s', tracker, repr(parsed))
                if parsed.get('ok'):
                    return parsed
                if 'rate_limited' in parsed:
                    raise SlackRateLimited()
                if 'auth' in parsed.get('error', ''):
                    raise SlackAuthError(parsed)

                raise RuntimeError('invalid request')
        except SlackRateLimited:
            self.logger.warning('api_call %s: ratelimit hit', tracker)
            delay += parsed.get('Retry-After', 30)
            return await self.api_call(method, delay=delay, **kwargs)
        except (aiohttp.ClientError, ValueError, RuntimeError) as err:
            try:
                parsed = parsed or (await resp.text())
            except (NameError, aiohttp.ClientError):
                pass

            self.logger.error(
                'api_call %s: failed with %s, method=%s, kwargs=%s, parsed=%s',
                tracker, repr(err), method, kwargs, parsed)
        raise SlackAPIError(parsed)

    def send_message(self, *, channel, text, as_user=True, attachments=None,
                     link_names=True, username=None, icon_url=None):
        """send a message to a channel keeping the sequence

        `await slackrtm.send_message(<...>)`
        could be split into
            `sending_status = slackrtm.send_message(<...>)`
            `await sending_status`

        Args:
            channel (str): channel, group or direct message identifier
            text (str): message content
            as_user (bool): send a message as the bot user
            attachments (list): see `api.slack.com/docs/message-formatting`
            link_names (bool): create links from @username mentions
            username (bool): use a custom sender name
            icon_url (str): a custom profile picture of the sender

        Returns:
            sync.sending_queue.Status: tracker for the scheduled task which
             returns a boolean value when finished: True on success else False.
        """
        queue = self._cache_sending_queue.get(channel)

        kwargs = dict(channel=channel, as_user=as_user, link_names=link_names,
                      username=username, icon_url=icon_url)

        while len(text) > 3999:
            first_part = text[:3999].rsplit('\n', 1)[0]
            queue.schedule(text=first_part, **kwargs)
            text = text[len(first_part):]

        status = queue.schedule(text=text, attachments=attachments, **kwargs)
        return status

    async def get_slack1on1(self, userid):
        """get the private slack channel with a given user from cache or request

        Args:
            userid (str): slack user_id

        Returns:
            str: identifier for the direct message channel

        Raises:
            SlackAPIError: could not create a 1on1
        """
        if userid not in self.users:
            self.users[userid] = {}
        if '1on1' not in self.users[userid]:
            channel = (await self.api_call('im.open', user=userid))['channel']
            self.users[userid]['1on1'] = channel['id']
        return self.users[userid]['1on1']

    async def update_cache(self, type_):
        """update the cached data from api-source

        Args:
            type_ (str): 'users', 'groups', 'channels', 'team', 'ims'
        """
        method = ('team.info' if type_ == 'team' else
                  'im.list' if type_ == 'ims' else type_ + '.list')
        try:
            response = await self.api_call(method)
        except SlackAPIError:
            # the raw exception with more details is already logged
            self.logger.info('cache update for %s failed', type_)
            return

        data_key = 'members' if type_ == 'users' else type_
        data = response[data_key]

        if type_ == 'team':
            self.team = data
        elif type_ == 'ims':
            for item in data:
                if item['user'] in self.users:
                    self.users[item['user']]['1on1'] = item['id']
                else:
                    self.users[item['user']] = {'1on1': item['id']}
        else:
            storage = self.users if type_ == 'users' else self.conversations
            for item in data:
                if item['id'] in storage:
                    storage[item['id']].update(item)
                else:
                    storage[item['id']] = item

    def get_channel_users(self, channel):
        """get the usernames and realnames of users attending the given channel

        Args:
            channel (str): channel or group identifier

        Returns:
            dict: with keys 'username slackid', realnames as values
                or the default value if no users can be fetched for the channel
        """
        channelusers = self._get_channel_data(channel, 'members', None)
        if channelusers is None:
            return {}

        users = {}
        for user_id in channelusers:
            username = self.get_username(user_id)
            if username:
                realname = self.get_realname(user_id, "No real name")
                users[username + " " + user_id] = realname
        return users

    def _get_user_data(self, user, key, default=None):
        """get user info described by the given key

        Args:
            user (str): user_id
            key (str): data entry in the user data
            default (unknown): value for missing user

        Returns:
            unknown: or the default value
        """
        if user not in self.users:
            self.logger.debug('user %s not found, reloading users', user)
            asyncio.ensure_future(self.update_cache('users'))
            return default
        return self.users[user].get(key, default)

    def _get_channel_data(self, channel, key, default=None):
        """fetch channel info from cache or pull all data once

        Args:
            channel (str): channel or group identifier
            key (str): data entry in the channel data
            default (unknown): return value if no data is available

        Returns:
            dict: requested channel entry or the default value
        """
        if channel not in self.conversations:
            type_ = 'channels' if channel.startswith('C') else 'groups'
            self.logger.debug('%s not found, reloading %s', channel, type_)
            asyncio.ensure_future(self.update_cache(type_))
            return default
        return self.conversations[channel].get(key, default)

    def get_realname(self, user, default=None):
        """get the users real name or return the default value

        Args:
            user (str): user_id
            default (unknwon): value for missing user or no available name

        Returns:
            str: the realname or the default value in case of a missing user
        """
        return self._get_user_data(user, 'real_name', default)

    def get_username(self, user, default=None):
        """get the users nickname or return the default value

        Args:
            user (str): user_id
            default (unknwon): value for missing user

        Returns:
            str: the nickname or the default value in case of a missing user
        """
        return self._get_user_data(user, 'name', default)

    def get_user_picture(self, user, default=None):
        """get the profile picture of the user or return the default value

        Args:
            user (str): user_id
            default (unknwon): value for missing user

        Returns:
            str: the image url or the default value in case of a missing user
        """
        return self._get_user_data(user, 'image_original', default)

    def get_chatname(self, channel, default=None):
        """get the name of a given channel and use the default as fallback

        Args:
            channel (str): a slack channel/group/dm
            default (unknwon): the fallback for a missing channel in the cache

        Returns:
            str: the chattitle or the default value in case of a missing chat
        """
        if channel.startswith('D'):
            # dms have no custom name
            return 'DM'
        return self._get_channel_data(channel, 'name', default=default)

    def get_syncs(self, channelid=None, hangoutid=None):
        """search for syncs with mathing channel or hangout identifier

        Args:
            channelid (str): slack channel identifier
            hangoutid (str): hangouts conversation identifier

        Returns:
            list: a list of dicts, each has two keys `channelid`, `hangoutid`
        """
        syncs = []
        for sync in self.syncs:
            if channelid == sync['channelid']:
                syncs.append(sync)
            elif hangoutid == sync['hangoutid']:
                syncs.append(sync)
        return syncs

    def config_syncto(self, channel, hangoutid):
        """add a new sync to the memory

        Args:
            channel (str): slack channel identifier
            hangoutid (str): hangouts conversation identifier

        Raises:
            AlreadySyncingError: the sync already exists
        """
        for sync in self.syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                raise AlreadySyncingError

        new_sync = {'channelid': channel, 'hangoutid': hangoutid}
        self.logger.info('adding sync: %s', new_sync)
        self.syncs.append(new_sync)
        self.bot.memory.save()
        return

    def config_disconnect(self, channel, hangoutid):
        """remove a sync from the memory

        Args:
            channel (str): slack channel identifier
            hangoutid (str): hangouts conversation identifier

        Raises:
            NotSyncingError: the sync does not exists
        """
        sync = None
        for sync in self.syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                self.logger.info('removing running sync: %s', sync)
                self.syncs.remove(sync)
        if not sync:
            raise NotSyncingError

        self.bot.memory.save()
        return

    async def _process_websocket(self, url):
        """read and process events from a slack websocket

        Args:
            url (str): websocket target URI

        Raises:
            WebsocketFailed: websocket connection failed or too many
                invalid events received from slack
            any exception that is not covered in `.handle_reply`
        """
        try:
            async with self._session.ws_connect(url, heartbeat=30) as websocket:
                self.logger.info('started new SlackRTM connection')

                soft_reset = 0
                while soft_reset < 5:
                    try:
                        reply = await websocket.receive_json()
                        if not reply:
                            # gracefully stopped
                            return
                        if 'type' not in reply:
                            raise ValueError('reply has no `type` entry: %s'
                                             % repr(reply))
                    except (ValueError, TypeError) as err:
                        # covers invalid json-replys and replys without a `type`
                        self.logger.warning('bad websocket read: %s', repr(err))
                        soft_reset += 1
                        await asyncio.sleep(2**soft_reset)
                        continue

                    await self._handle_slack_message(reply)

                    # valid response handled, leave fail-state
                    soft_reset = 0

        except aiohttp.ClientError as err:
            self.logger.error('websocket connection failed: %s', repr(err))

        # can not connect or permanent websocket read error
        raise WebsocketFailed()

    async def _handle_slack_message(self, reply):
        """parse and forward a response from slack

        Args:
            reply (dict): responce from slack
        """
        async def _update_cache_on_event(event_type):
            """update the internal cache based on team changes

            Args:
                event_type (str): see https://api.slack.com/rtm for details

            Returns:
                boolean: True if the reply triggered an update only
            """
            if event_type in _CACHE_UPDATE_USERS:
                await self.update_cache('users')
            elif event_type in _CACHE_UPDATE_CHANNELS:
                await self.update_cache('channels')
                return event_type in _CACHE_UPDATE_CHANNELS_HIDDEN
            elif event_type in _CACHE_UPDATE_GROUPS:
                await self.update_cache('groups')
                return event_type in _CACHE_UPDATE_GROUPS_HIDDEN
            elif event_type in _SYSTEM_MESSAGES:
                return True
            elif event_type in _CACHE_UPDATE_TEAM:
                await self.update_cache('team')
                await self.rebuild_base()
            else:
                return False
            return True

        self.logger.debug('received reply %s', repr(reply))

        if (await _update_cache_on_event(reply['type'])
                # no message content
                or await _update_cache_on_event(reply.get('subtype'))
                # we do not sync this type
                or reply.get('is_ephemeral') or reply.get('hidden')):
                # hidden message from slack
            self.logger.debug('reply is system event')
            return

        if (('user' in reply and reply['user'] == self.my_uid) or
                ('bot_id' in reply and reply['bot_id'] == self.my_bid)):
            # message from the bot user, skip it as we already handled it
            self.logger.debug('reply content already seen')
            return

        error_message = 'error while parsing a Slack reply\nreply=%s'
        error_is_critical = True
        try:
            msg = SlackMessage(self, reply)

            error_message = 'error in command handling\nreply=%s'
            error_is_critical = False
            await slack_command_handler(self, msg)
        except (ParseError, IgnoreMessage) as err:
            self.logger.debug(repr(err))
            return
        except SlackAuthError as err:
            self.logger.critical(repr(err))
            # continue with message handling
        except:
            self.logger.exception(error_message, repr(reply))
            if error_is_critical:
                return

        syncs = self.get_syncs(channelid=msg.channel)
        if not syncs:
            # stop processing replies if no syncs are available (optimisation)
            return

        segments = msg.segments
        channel_name = msg.title
        channel_tag = '%s:%s' % (self.identifier, msg.channel)

        if msg.file_attachment:
            image = self.bot.sync.get_sync_image(
                url=msg.file_attachment,
                headers={'Authorization': 'Bearer ' + self.apikey})
        else:
            image = None

        for sync in syncs:
            if msg.is_joinleave is not None:
                asyncio.ensure_future(self.bot.sync.membership(
                    identifier=channel_tag, conv_id=sync['hangoutid'],
                    user=msg.user, text=segments, title=channel_name,
                    type_=msg.is_joinleave,
                    participant_user=msg.participant_user))
                continue

            asyncio.ensure_future(self.bot.sync.message(
                identifier=channel_tag, conv_id=sync['hangoutid'],
                user=msg.user, text=segments, image=image,
                edited=msg.edited, title=channel_name))

    async def _handle_sync_message(self, bot, event):
        """forward message/media from any platform to slack

        Args:
            bot (hangupsbot.HangupsBot): the running instance
            event (sync.event.SyncEvent): instance to be handled
        """
        photo_url = ('https:' + event.user.photo_url
                     if isinstance(event.user.photo_url, str) else None)

        for sync in self.get_syncs(hangoutid=event.conv_id):
            channel_tag = '%s:%s' % (self.identifier, sync['channelid'])
            if channel_tag in event.previous_targets:
                continue
            event.previous_targets.add(channel_tag)

            message = event.get_formated_text(style=SLACK_STYLE,
                                              conv_id=channel_tag)

            image_url = await event.get_image_url(channel_tag)
            if image_url is not None:
                message += '\n' + image_url

            displayname = event.user.get_displayname(channel_tag,
                                                     text_only=True)
            if (get_sync_config_entry(bot, channel_tag, 'sync_title') and
                    event.title(channel_tag)):
                displayname = '%s (%s)' % (displayname,
                                           event.title(channel_tag))

            self.send_message(channel=sync['channelid'], text=message,
                              username=displayname, icon_url=photo_url,
                              as_user=event.user.is_self)

    def _handle_sync_membership(self, dummy, event):
        """notify configured slack channels about a membership change

        Args:
            dummy (hangupsbot.HangupsBot): unused
            event (sync.event.SyncEventMembership): instance to be handled
        """
        for sync in self.get_syncs(hangoutid=event.conv_id):
            channel_tag = '%s:%s' % (self.identifier, sync['channelid'])
            if channel_tag in event.previous_targets:
                continue
            event.previous_targets.add(channel_tag)

            message = event.get_formated_text(style=SLACK_STYLE,
                                              conv_id=channel_tag)
            if message is None:
                # membership change should not be synced to this channel
                return

            self.send_message(channel=sync['channelid'], text=message)

    def _handle_ho_rename(self, bot, event):
        """notify configured slack channels about a changed conversation name

        Args:
            bot (hangupsbot.HangupsBot): the running instance
            event (event.ConversationEvent): instance to be handled
        """
        name = bot.conversations.get_name(event.conv)
        user = SyncUser(bot, user_id=event.user_id.chat_id)

        for sync in self.get_syncs(hangoutid=event.conv_id):
            channel_tag = '%s:%s' % (self.identifier, sync['channelid'])
            message = _RENAME_TEMPLATE.format(
                chat_id=user.id_.chat_id,
                name=user.get_displayname(channel_tag, text_only=True),
                new_name=name)
            self.send_message(channel=sync['channelid'], text=message)

    async def _handle_profilesync(self, platform, remote_user, conv_1on1,
                                  split_1on1s):
        """finish profile sync and set a 1on1 sync if requested

        Args:
            platform (str): sync platform identifier
            remote_user (str): user who startet the sycn on a given platform
            conv_1on1 (str): users 1on1 in hangouts
            split_1on1s (boolean): toggle to sync the private chats
        """
        if platform != self.identifier:
            return

        slack_user_id = remote_user
        if split_1on1s:
            # delete an existing sync
            try:
                self.config_disconnect(
                    await self.get_slack1on1(slack_user_id), conv_1on1)
            except NotSyncingError:
                pass
            text = _('*Your profiles are connected and you will not receive my '
                     'messages in Slack.*')

            private_chat = await self.get_slack1on1(slack_user_id)
            self.send_message(channel=private_chat, text=text)
        else:
            # setup a chat sync
            try:
                self.config_syncto(
                    await self.get_slack1on1(slack_user_id), conv_1on1)
            except AlreadySyncingError:
                pass
            text = _('*Your profiles are connected and you will receive my '
                     'messages in Slack as well.*')

        await self.bot.coro_send_message(conv_1on1, text)

    def __del__(self):
        if self._session is not None:
            self._session.close()
