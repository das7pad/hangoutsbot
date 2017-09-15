import asyncio
import logging
import mimetypes
import os
import re
import urllib.request

import aiohttp
import hangups
import emoji

import hangups_shim as hangups

from .bridgeinstance import (
    BridgeInstance,
    FakeEvent,
)
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
)
from .message import SlackMessage
from .parsers import (
    slack_markdown_to_hangups,
    hangups_markdown_to_slack,
)
from .storage import (
    slackrtm_conversations_set,
    slackrtm_conversations_get,
)


logger = logging.getLogger(__name__)

# fix for simple_smile support
emoji.EMOJI_UNICODE[':simple_smile:'] = emoji.EMOJI_UNICODE[':smiling_face:']
emoji.EMOJI_ALIAS_UNICODE[':simple_smile:'] = emoji.EMOJI_UNICODE[':smiling_face:']

REFFMT = re.compile(r'<((.)([^|>]*))((\|)([^>]*)|([^>]*))>')

class SlackRTMSync(object):
    def __init__(self, slackrtm, channelid, hangoutid, hotag, slacktag, sync_joins=True, showslackrealnames=False, showhorealnames="real"):
        self.channelid = channelid
        self.hangoutid = hangoutid
        self.hotag = hotag
        self.sync_joins = sync_joins
        self.slacktag = slacktag
        self.showslackrealnames = showslackrealnames
        self.showhorealnames = showhorealnames
        if self.slacktag == 'NOT_IN_CONFIG':
            self.slacktag = slackrtm.get_teamname()
        self.team_name = slackrtm.name # chatbridge needs this for context

        self._bridgeinstance = BridgeInstance(slackrtm.bot, "slackrtm")

        self._bridgeinstance.set_extra_configuration(hangoutid, channelid)

    @staticmethod
    def from_dict(slackrtm, sync_dict):
        sync_joins = True
        if 'sync_joins' in sync_dict and not sync_dict['sync_joins']:
            sync_joins = False
        slacktag = None
        if 'slacktag' in sync_dict:
            slacktag = sync_dict['slacktag']
        else:
            slacktag = 'NOT_IN_CONFIG'
        slackrealnames = True
        if 'showslackrealnames' in sync_dict and not sync_dict['showslackrealnames']:
            slackrealnames = False
        horealnames = 'real'
        if 'showhorealnames' in sync_dict:
            horealnames = sync_dict['showhorealnames']
        return SlackRTMSync(slackrtm,
                            sync_dict['channelid'],
                            sync_dict['hangoutid'],
                            sync_dict['hotag'],
                            slacktag,
                            sync_joins,
                            slackrealnames,
                            horealnames)

    def to_dict(self):
        return {
            'channelid': self.channelid,
            'hangoutid': self.hangoutid,
            'hotag': self.hotag,
            'sync_joins': self.sync_joins,
            'slacktag': self.slacktag,
            'showslackrealnames': self.showslackrealnames,
            'showhorealnames': self.showhorealnames,
            }

    def get_printable_options(self):
        return 'hotag=%s, sync_joins=%s, slacktag=%s, showslackrealnames=%s, showhorealnames="%s"' % (
            '"{}"'.format(self.hotag) if self.hotag else 'NONE',
            self.sync_joins,
            '"{}"'.format(self.slacktag) if self.slacktag else 'NONE',
            self.showslackrealnames,
            self.showhorealnames,
            )


class SlackRTM(object):
    """hander for a single slack team

    Args:
        bot: HangupsBot instance
        sink_config: dict, basic configuration including the api `key`, a
            `name` for the team and `admins` a list of slack user ids
    """
    _session = None
    logger = logger

    def __init__(self, bot, sink_config):
        self.bot = bot
        self.config = sink_config
        self.apikey = self.config['key']
        self.slack_domain = None
        self.conversations = {}
        self.userinfos = {}
        self.my_uid = None
        self.identifier = None
        self.name = None
        self.team = {}
        self.syncs = []
        self._session = aiohttp.ClientSession()

    @property
    def admins(self):
        """get the configured admins

        Returns:
            list of strings, a list of slack user ids
        """
        return self.config.get('admins', [])

    async def start(self):
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
            return login_data

        async def _build_cache(login_data):
            """set the team; fetch users, channels and groups

            Args:
                login_data (dict): slack-api response of `rtm.connect`, which
                    contains the team data in the entry `team`
            """
            self.team = login_data['team']
            await asyncio.gather(*(self.update_cache(name)
                                   for name in ('users', 'channels', 'groups')))

        def _set_selfuser_and_id(login_data):
            """set the bot user

            .rebuild_base() requires the self user being present

            Args:
                login_data (dict): slack-api response of `rtm.connect`, which
                    contains the bot user object in the entry `self`
            """
            self.my_uid = login_data['self']['id']
            self.userinfos[self.my_uid] = login_data['self']


        hard_reset = 0
        while hard_reset < 5:
            try:
                await asyncio.sleep(hard_reset*10)
                hard_reset += 1

                login_data = await _login()

                await _build_cache(login_data)
                _set_selfuser_and_id(login_data)
                self.rebuild_base()

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
                self.close()

        self.logger.critical('ran out of retries, closing the connection')

    def rebuild_base(self):
        """reset everything that is based on the sink config or team data"""
        bot_username = self.get_username(self.my_uid)
        self.slack_domain = self.team['domain']

        if 'name' in self.config:
            self.name = self.config['name']
        else:
            self.name = '%s@%s' % (bot_username, self.slack_domain)
            logger.warning('no name set in config file, using computed name %s',
                           self.name)

        self.identifier = 'slackrtm:%s' % self.slack_domain
        self.logger = logging.getLogger('plugins.slackrtm.%s'
                                        % self.slack_domain)

        for admin in self.admins:
            if admin not in self.userinfos:
                self.logger.warning('admin userid %s not found in user list',
                                    admin)
        if not self.admins:
            self.logger.warning('no admins specified in config file')

        syncs = slackrtm_conversations_get(self.bot, self.name)

        for sync in syncs:
            sync = SlackRTMSync.from_dict(self, sync)
            self.syncs.append(sync)

    async def api_call(self, method, **kwargs):
        """perform an api call to slack

        more documentation on the api call: https://api.slack.com/web
        more documentation on methods: https://api.slack.com/methods

        delay the execution in case of a ratelimit

        Args:
            method: the api-method to call
            kwargs: optional kwargs passed with api-method

        Returns:
            dict, pre-parsed json response

        Raises:
            SlackAPIError: invalid request
            SlackAuthError: the token got revoked
        """
        delay = kwargs.pop('delay', 0)
        await asyncio.sleep(delay)
        parsed = None
        try:
            async with await asyncio.shield(self._session.post(
                'https://slack.com/api/' + method,
                data={'token': self.apikey, **kwargs})) as resp:

                parsed = await resp.json()
                if parsed.get('ok'):
                    return parsed
                if 'rate_limited' in parsed:
                    raise SlackRateLimited()
                if 'auth' in parsed.get('error', ''):
                    raise SlackAuthError(parsed)

                raise RuntimeError('invalid request')
        except SlackRateLimited:
            self.logger.warning('ratelimit reached\n%s', parsed)
            delay += parsed.get('Retry-After', 30)
            return await self.api_call(method, delay=delay, **kwargs)
        except (aiohttp.ClientError, ValueError, RuntimeError) as err:
            try:
                parsed = parsed or (await resp.text())
            except (NameError, aiohttp.ClientError):
                pass

            self.logger.error(
                'api_call failed: %s, method=%s, kwargs=%s, parsed=%s',
                repr(err), method, kwargs, parsed)
        raise SlackAPIError(parsed)

    async def send_message(self, **kwargs):
        """send the content to slack

        Args:
            kwargs (dict): see api documentation for `chat.postMessage`

        Returns:
            boolean: True in case of a successful api-call, otherwise False

        Raises:
            SlackAuthError: the api-token got revoked
        """
        self.logger.debug("sending to channel/group %s: %s",
                          kwargs.get('channel'), kwargs.get('text'))
        try:
            await self.api_call('chat.postMessage', **kwargs)
        except SlackAPIError:
            # already logged
            return False
        else:
            return True

    async def get_slack1on1(self, userid):
        if not userid in self.conversations:
            self.conversations[userid] = (await self.api_call('im.open', user=userid))['channel']
        return self.conversations[userid]['id']

    async def update_cache(self, type_):
        """update the cached data from api-source

        Args:
            type_: string, 'users', 'groups', 'channels', 'team'
        """
        method = ('team.info' if type_ == 'team' else type_ + '.list')
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
        else:
            storage = self.userinfos if type_ == 'users' else self.conversations
            storage.update({item['id']: item for item in data})

    async def get_channel_users(self, channelid, default=None):
        channelusers = self._get_channel_data(channelid, 'members', None)
        if channelusers is None:
            return default

        users = {}
        for user in channelusers:
            username = self.get_username(user)
            realname = self.get_realname(user, "No real name")
            if username:
                users[username+" "+user] = realname

        return users

    def get_teamname(self):
        # team info is static, no need to update
        return self.team['name']

    def _get_user_data(self, user, key, default=None):
        """get user info described by the given key

        Args:
            user: string, user_id
            key: string, data entry in the user data
            default: any type, value for missing user

        Returns:
            any type, or the default value
        """
        if user not in self.userinfos:
            self.logger.debug('user %s not found, reloading users', user)
            asyncio.ensure_future(self.update_cache('users'))
            return default
        return self.userinfos[user].get(key, default)

    def _get_channel_data(self, channel, key, default=None):
        """fetch channel info from cache or pull all data once

        Args:
            channel: string, channel or group identifier
            key: string, data entry in the channel data
            default: value to return if no data is available for the channel

        Returns:
            dict with info about the channel or the default value
        """
        if channel not in self.conversations:
            type_ = 'channels' if channel.startswith('C') else 'groups'
            self.logger.debug('%s not found, reloading %s', channel, type_)
            asyncio.ensure_future(self.update_cache(type_))
            return default
        return self.conversations[channel].get(key, default)

    def get_realname(self, user, default=None):
        return self._get_user_data(user, 'real_name', default)

    def get_username(self, user, default=None):
        return self._get_user_data(user, 'name', default)

    def get_user_picture(self, user, default=None):
        """get the profile picture of the user or return the default value

        Args:
            user (str): user_id
            default (unknwon): value for missing user

        Returns:
            str: the image url or the default value
        """
        return self._get_user_data(user, 'image_original', default)

    def get_chatname(self, channel, default=None):
        if channel.startswith('D'):
            # dms have no custom name
            return 'DM'
        return self._get_channel_data(channel, 'name', default=default)

    def get_syncs(self, channelid=None, hangoutid=None):
        syncs = []
        for sync in self.syncs:
            if channelid == sync.channelid:
                syncs.append(sync)
            elif hangoutid == sync.hangoutid:
                syncs.append(sync)
        return syncs

    def match_reference(self, match):
        out = ""
        linktext = ""
        if match.group(5) == '|':
            linktext = match.group(6)
        if match.group(2) == '@':
            if linktext != "":
                out = linktext
            else:
                out = "@%s" % self.get_username(match.group(3),
                                                'unknown:%s' % match.group(3))
        elif match.group(2) == '#':
            if linktext != "":
                out = "#%s" % linktext
            else:
                out = "#%s" % self.get_chatname(match.group(3),
                                                'unknown:%s' % match.group(3))
        else:
            linktarget = match.group(1)
            if linktext == "":
                linktext = linktarget
            out = '[{}]({})'.format(linktext, linktarget)
        out = out.replace('_', '%5F')
        out = out.replace('*', '%2A')
        out = out.replace('`', '%60')
        return out

    @asyncio.coroutine
    def upload_image(self, image_uri, sync, username, userid, channel_name):
        token = self.apikey
        self.logger.info('downloading %s', image_uri)
        filename = os.path.basename(image_uri)
        request = urllib.request.Request(image_uri)
        request.add_header("Authorization", "Bearer %s" % token)
        image_response = urllib.request.urlopen(request)
        content_type = image_response.info().get_content_type()

        filename_extension = mimetypes.guess_extension(content_type).lower() # returns with "."
        physical_extension = "." + filename.rsplit(".", 1).pop().lower()

        if physical_extension == filename_extension:
            pass
        elif filename_extension == ".jpe" and physical_extension in [".jpg", ".jpeg", ".jpe", ".jif", ".jfif"]:
            # account for mimetypes idiosyncrancy to return jpe for valid jpeg
            pass
        else:
            self.logger.warning("unable to determine extension: %s %s", filename_extension, physical_extension)
            filename += filename_extension

        self.logger.info('uploading as %s', filename)
        image_id = yield from self.bot._client.upload_image(image_response, filename=filename)

        self.logger.info('sending HO message, image_id: %s', image_id)
        yield from sync._bridgeinstance._send_to_internal_chat(
            sync.hangoutid,
            "shared media from slack",
            {"sync": sync,
             "source_user": username,
             "source_uid": userid,
             "source_title": channel_name},
            image_id=image_id)

    def config_syncto(self, channel, hangoutid, shortname):
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                raise AlreadySyncingError

        sync = SlackRTMSync(self, channel, hangoutid, shortname, self.get_teamname())
        self.logger.info('adding sync: %s', sync.to_dict())
        self.syncs.append(sync)
        syncs = slackrtm_conversations_get(self.bot, self.name)
        self.logger.info('storing sync: %s', sync.to_dict())
        syncs.append(sync.to_dict())
        slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_disconnect(self, channel, hangoutid):
        sync = None
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                self.logger.info('removing running sync: %s', sync)
                sync._bridgeinstance.close()
                self.syncs.remove(sync)
        if not sync:
            raise NotSyncingError

        syncs = slackrtm_conversations_get(self.bot, self.name)
        for sync in syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                self.logger.info('removing stored sync: %s', sync)
                syncs.remove(sync)
        slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_setsyncjoinmsgs(self, channel, hangoutid, enable):
        sync = None
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                break
        if not sync:
            raise NotSyncingError

        self.logger.info('setting sync_joins=%s for sync=%s', enable, sync.to_dict())
        sync.sync_joins = enable

        syncs = slackrtm_conversations_get(self.bot, self.name)
        for sync in syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                syncs.remove(sync)
        self.logger.info('storing new sync=%s with changed sync_joins', sync)
        syncs.append(sync.to_dict())
        slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_sethotag(self, channel, hangoutid, hotag):
        sync = None
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                break
        if not sync:
            raise NotSyncingError

        self.logger.info('setting hotag="%s" for sync=%s', hotag, sync.to_dict())
        sync.hotag = hotag

        syncs = slackrtm_conversations_get(self.bot, self.name)
        for sync in syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                syncs.remove(sync)
        self.logger.info('storing new sync=%s with changed hotag', sync)
        syncs.append(sync.to_dict())
        slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_setslacktag(self, channel, hangoutid, slacktag):
        sync = None
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                break
        if not sync:
            raise NotSyncingError

        self.logger.info('setting slacktag="%s" for sync=%s', slacktag, sync.to_dict())
        sync.slacktag = slacktag

        syncs = slackrtm_conversations_get(self.bot, self.name)
        for sync in syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                syncs.remove(sync)
        self.logger.info('storing new sync=%s with changed slacktag', sync)
        syncs.append(sync.to_dict())
        slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_showslackrealnames(self, channel, hangoutid, realnames):
        sync = None
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                break
        if not sync:
            raise NotSyncingError

        self.logger.info('setting showslackrealnames=%s for sync=%s', realnames, sync.to_dict())
        sync.showslackrealnames = realnames

        syncs = slackrtm_conversations_get(self.bot, self.name)
        for sync in syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                syncs.remove(sync)
        self.logger.info('storing new sync=%s with changed hotag', sync)
        syncs.append(sync.to_dict())
        slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_showhorealnames(self, channel, hangoutid, realnames):
        sync = None
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                break
        if not sync:
            raise NotSyncingError

        self.logger.info('setting showhorealnames=%s for sync=%s', realnames, sync.to_dict())
        sync.showhorealnames = realnames

        syncs = slackrtm_conversations_get(self.bot, self.name)
        for sync in syncs:
            if sync['channelid'] == channel and sync['hangoutid'] == hangoutid:
                syncs.remove(sync)
        self.logger.info('storing new sync=%s with changed hotag', sync)
        syncs.append(sync.to_dict())
        slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    async def _process_websocket(self, url):
        """read and process events from a slack websocket

        Args:
            url: string, websocket target URI

        Raises:
            exceptions.WebsocketFailed: websocket connection failed or too many
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
                    except ValueError as err:
                        # covers json-decode errors and replys without a `type`
                        self.logger.warning('bad websocket read: %s', repr(err))
                        soft_reset += 1
                        await asyncio.sleep(2**soft_reset)
                        continue

                    await self.handle_reply(reply)

                    # valid response handled, leave fail-state
                    soft_reset = 0

        except aiohttp.ClientError as err:
            self.logger.error('websocket connection failed: %s', repr(err))

        # can not connect or permanent websocket read error
        raise WebsocketFailed()

    async def handle_reply(self, reply):
        """handle incoming replies from slack"""

        error_message = 'error while parsing a Slack reply\n%s'
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

        message = REFFMT.sub(self.match_reference, msg.text)
        message = slack_markdown_to_hangups(message)

        for sync in syncs:
            if not sync.sync_joins and msg.is_joinleave:
                continue

            if msg.from_ho_id != sync.hangoutid:
                username = msg.user.full_name if sync.showslackrealnames else msg.user.username
                channel_name = self.get_chatname(msg.channel)

                if msg.file_attachment:
                    asyncio.ensure_future(
                        self.upload_image(
                            msg.file_attachment,
                            sync,
                            username,
                            msg.user_id,
                            channel_name))

                asyncio.ensure_future(
                    sync._bridgeinstance._send_to_internal_chat(
                        sync.hangoutid,
                        message,
                        {"sync": sync,
                         "source_user": username,
                         "source_uid": msg.user_id,
                         "source_gid": sync.channelid,
                         "source_title": channel_name}))

    async def _send_deferred_media(self, image_link, sync, full_name, link_names, photo_url, fragment):
        await self.send_message(channel=sync.channelid,
                                text="{} {}".format(image_link, fragment),
                                username=full_name,
                                link_names=True,
                                icon_url=photo_url)

    async def handle_ho_message(self, event, conv_id, channel_id):
        user = event.passthru["original_request"]["user"]
        message = event.passthru["original_request"]["message"]

        if not message:
            message = ""

        message = hangups_markdown_to_slack(message)

        # NOTE:
        # slackrtm uses an overengineered pseudo SlackRTMSync "structure" to contain individual 1-1 syncs
        # we rely on the chatbridge to iterate through multiple syncs, and ensure we only have
        # to deal with a single mapping at this level
        # XXX: the mapping SHOULD BE single, but let duplicates get through

        active_syncs = []
        for sync in self.get_syncs(hangoutid=conv_id):
            if sync.channelid != channel_id:
                continue
            if sync.hangoutid != conv_id:
                continue
            active_syncs.append(sync)

        for sync in active_syncs:
            bridge_user = sync._bridgeinstance._get_user_details(user, {"event": event})

            extras = []
            if sync.showhorealnames == "nick":
                display_name = bridge_user["nickname"] or bridge_user["full_name"]
            else:
                display_name = bridge_user["full_name"]
                if (sync.showhorealnames == "both" and bridge_user["nickname"] and
                        not bridge_user["full_name"] == bridge_user["nickname"]):
                    extras.append(bridge_user["nickname"])

            if sync.hotag is True:
                if "chatbridge" in event.passthru and event.passthru["chatbridge"]["source_title"]:
                    chat_title = event.passthru["chatbridge"]["source_title"]
                    extras.append(chat_title)
            elif sync.hotag:
                extras.append(sync.hotag)

            if extras:
                display_name = "{} ({})".format(display_name, ", ".join(extras))

            slackrtm_fragment = "<ho://{}/{}| >".format(conv_id, bridge_user["chat_id"] or bridge_user["preferred_name"])

            # XXX: media sending:
            # * if media link is already available, send it immediately
            #   * real events from google servers will have the medialink in event.conv_event.attachment
            #   * media link can also be added as part of the passthru
            # * for events raised by other external chats, wait for the public link to become available


            if "attachments" in event.passthru["original_request"] and event.passthru["original_request"]["attachments"]:
                # automatically prioritise incoming events with attachments available
                media_link = event.passthru["original_request"]["attachments"][0]
                self.logger.info("media link in original request: %s", media_link)

                message = "shared media: {}".format(media_link)

            elif isinstance(event, FakeEvent):
                if ("image_id" in event.passthru["original_request"]
                        and event.passthru["original_request"]["image_id"]):
                    # without media link, create a deferred post until a public media link becomes available
                    image_id = event.passthru["original_request"]["image_id"]
                    self.logger.info("wait for media link: %s", image_id)

                    asyncio.ensure_future(
                        self.bot._handlers.image_uri_from(
                            image_id,
                            self._send_deferred_media,
                            sync,
                            display_name,
                            True,
                            bridge_user["photo_url"],
                            slackrtm_fragment))

            elif (hasattr(event, "conv_event")
                  and hasattr(event.conv_event, "attachments")
                  and len(event.conv_event.attachments) == 1):
                # catch actual events with media link  but didn' go through the passthru
                media_link = event.conv_event.attachments[0]
                self.logger.info("media link in original event: %s", media_link)

                message = "shared media: {}".format(media_link)

            # standard message relay

            message = "{} {}".format(message, slackrtm_fragment)

            self.logger.info("message %s: %s", sync.channelid, message)
            await self.send_message(channel=sync.channelid,
                                    text=message,
                                    username=display_name,
                                    link_names=True,
                                    icon_url=bridge_user["photo_url"])

    async def handle_ho_membership(self, event):
        # Generate list of added or removed users
        links = []
        for user_id in event.conv_event.participant_ids:
            user = event.conv.get_user(user_id)
            links.append(u'<https://plus.google.com/%s/about|%s>' % (user.id_.chat_id, user.full_name))
        names = u', '.join(links)

        for sync in self.get_syncs(hangoutid=event.conv_id):
            if not sync.sync_joins:
                continue
            if sync.hotag:
                honame = sync.hotag
            else:
                honame = self.bot.conversations.get_name(event.conv)
            # JOIN
            if event.conv_event.type_ == hangups.MembershipChangeType.JOIN:
                invitee = u'<https://plus.google.com/%s/about|%s>' % (event.user_id.chat_id, event.user.full_name)
                if invitee == names:
                    message = u'%s has joined %s' % (invitee, honame)
                else:
                    message = u'%s has added %s to %s' % (invitee, names, honame)
            # LEAVE
            else:
                message = u'%s has left _%s_' % (names, honame)
            message = u'%s <ho://%s/%s| >' % (message, event.conv_id, event.user_id.chat_id)
            self.logger.debug("sending to channel/group %s: %s", sync.channelid, message)
            await self.send_message(channel=sync.channelid,
                                    text=message,
                                    as_user=True,
                                    link_names=True)

    async def handle_ho_rename(self, event):
        name = self.bot.conversations.get_name(event.conv)

        for sync in self.get_syncs(hangoutid=event.conv_id):
            invitee = u'<https://plus.google.com/%s/about|%s>' % (event.user_id.chat_id, event.user.full_name)
            hotagaddendum = ''
            if sync.hotag:
                hotagaddendum = ' _%s_' % sync.hotag
            message = u'%s has renamed the Hangout%s to _%s_' % (invitee, hotagaddendum, name)
            message = u'%s <ho://%s/%s| >' % (message, event.conv_id, event.user_id.chat_id)
            self.logger.debug("sending to channel/group %s: %s", sync.channelid, message)
            await self.send_message(channel=sync.channelid,
                                    text=message,
                                    as_user=True,
                                    link_names=True)

    def close(self):
        self.logger.debug("closing all bridge instances")
        for sync in self.syncs:
            sync._bridgeinstance.close()

    def __del__(self):
        self.close()

        if self._session is not None:
            self._session.close()
