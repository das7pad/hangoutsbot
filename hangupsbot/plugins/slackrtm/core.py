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
from .commands_slack import slackCommandHandler
from .exceptions import (
    AlreadySyncingError,
    NotSyncingError,
    IgnoreMessage,
    ParseError,
    IncompleteLoginError,
    WebsocketFailed,
)
from .message import SlackMessage
from .parsers import (
    slack_markdown_to_hangups,
    hangups_markdown_to_slack,
)
from .utils import (
    _slackrtms,
    _slackrtm_conversations_set,
    _slackrtm_conversations_get,
)


logger = logging.getLogger(__name__)

# fix for simple_smile support
emoji.EMOJI_UNICODE[':simple_smile:'] = emoji.EMOJI_UNICODE[':smiling_face:']
emoji.EMOJI_ALIAS_UNICODE[':simple_smile:'] = emoji.EMOJI_UNICODE[':smiling_face:']

REFFMT = re.compile(r'<((.)([^|>]*))((\|)([^>]*)|([^>]*))>')

class SlackRTMSync(object):
    def __init__(self, hangoutsbot, channelid, hangoutid, hotag, slacktag, sync_joins=True, image_upload=True, showslackrealnames=False, showhorealnames="real"):
        self.channelid = channelid
        self.hangoutid = hangoutid
        self.hotag = hotag
        self.sync_joins = sync_joins
        self.image_upload = image_upload
        self.slacktag = slacktag
        self.showslackrealnames = showslackrealnames
        self.showhorealnames = showhorealnames
        self.team_name = None

        self._bridgeinstance = BridgeInstance(hangoutsbot, "slackrtm")

        self._bridgeinstance.set_extra_configuration(hangoutid, channelid)

    @staticmethod
    def fromDict(hangoutsbot, sync_dict):
        sync_joins = True
        if 'sync_joins' in sync_dict and not sync_dict['sync_joins']:
            sync_joins = False
        image_upload = True
        if 'image_upload' in sync_dict and not sync_dict['image_upload']:
            image_upload = False
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
        return SlackRTMSync( hangoutsbot,
                             sync_dict['channelid'],
                             sync_dict['hangoutid'],
                             sync_dict['hotag'],
                             slacktag,
                             sync_joins,
                             image_upload,
                             slackrealnames,
                             horealnames)

    def toDict(self):
        return {
            'channelid': self.channelid,
            'hangoutid': self.hangoutid,
            'hotag': self.hotag,
            'sync_joins': self.sync_joins,
            'image_upload': self.image_upload,
            'slacktag': self.slacktag,
            'showslackrealnames': self.showslackrealnames,
            'showhorealnames': self.showhorealnames,
            }

    def getPrintableOptions(self):
        return 'hotag=%s, sync_joins=%s, image_upload=%s, slacktag=%s, showslackrealnames=%s, showhorealnames="%s"' % (
            '"{}"'.format(self.hotag) if self.hotag else 'NONE',
            self.sync_joins,
            self.image_upload,
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
        self.lastimg = ''
        self._login_data = {}
        self.conversations = {}
        self.userinfos = {}
        self.my_uid = None
        self.name = None
        self.team = {}
        self.admins = []
        self.syncs = []

    async def start(self):
        self._session = aiohttp.ClientSession()
        self._login_data = await self.api_call('rtm.connect')

        for key in ('self', 'team', 'url'):
            if key not in self._login_data:
                raise IncompleteLoginError

        if 'name' in self.config:
            self.name = self.config['name']
        else:
            self.name = '%s@%s' % (self._login_data['self']['name'],
                                   self._login_data['team']['domain'])
            logger.warning('no name set in config file, using computed name %s',
                           self.name)
        self.logger = logging.getLogger('plugins.slackrtm.%s' % self.name)

        await self.update_userinfos()
        await self.update_channelinfos()
        await self.update_groupinfos()
        await self.update_teaminfos()
        self.my_uid = self._login_data['self']['id']

        if 'admins' in self.config:
            for a in self.config['admins']:
                if a not in self.userinfos:
                    self.logger.warning('userid %s not found in user list, ignoring', a)
                else:
                    self.admins.append(a)
        if not len(self.admins):
            self.logger.warning('no admins specified in config file')

        syncs = _slackrtm_conversations_get(self.bot, self.name)

        for s in syncs:
            sync = SlackRTMSync.fromDict(self.bot, s)
            if sync.slacktag == 'NOT_IN_CONFIG':
                sync.slacktag = self.get_teamname()
            sync.team_name = self.name # chatbridge needs this for context
            self.syncs.append(sync)

        try:
            await self._process_websocket(self._login_data['url'])
        except WebsocketFailed:
            self.logger.critical('closing SlackRTM')
            return
        except:                                     # pylint:disable=bare-except
            self.logger.exception('core error')
        finally:
            self.close()
        return await self.start()

    async def api_call(self, method, **kwargs):
        response = await self._session.post(
            'https://slack.com/api/' + method,
            data={'token': self.apikey, **kwargs})
        return await response.json()

    async def get_slack1on1(self, userid):
        if not userid in self.conversations:
            self.conversations[userid] = (await self.api_call('im.open', user=userid))['channel']
        return self.conversations[userid]['id']

    async def update_userinfos(self, users=None):
        if users is None:
            response = await self.api_call('users.list')
            users = response['members']
        userinfos = {}
        for u in users:
            userinfos[u['id']] = u
        self.userinfos = userinfos

    async def get_channel_users(self, channelid, default=None):
        channelinfo = None
        if channelid.startswith('C'):
            if not channelid in self.conversations:
                await self.update_channelinfos()
            if not channelid in self.conversations:
                self.logger.error('get_channel_users: Failed to find channel %s' % channelid)
                return None
            else:
                channelinfo = self.conversations[channelid]
        else:
            if not channelid in self.conversations:
                await self.update_groupinfos()
            if not channelid in self.conversations:
                self.logger.error('get_channel_users: Failed to find private group %s' % channelid)
                return None
            else:
                channelinfo = self.conversations[channelid]

        channelusers = channelinfo['members']
        users = {}
        for u in channelusers:
            username = self.get_username(u)
            realname = self.get_realname(u, "No real name")
            if username:
                users[username+" "+u] = realname

        return users

    async def update_teaminfos(self, team=None):
        if team is None:
            response = await self.api_call('team.info')
            team = response['team']
        self.team = team

    def get_teamname(self):
        # team info is static, no need to update
        return self.team['name']

    def get_slack_domain(self):
        # team info is static, no need to update
        return self.team['domain']

    def get_realname(self, user, default=None):
        if user not in self.userinfos:
            self.logger.debug('user %s not found', user)
            asyncio.ensure_future(self.update_userinfos())
            return default
        if not self.userinfos[user]['real_name']:
            return default
        return self.userinfos[user]['real_name']


    def get_username(self, user, default=None):
        if user not in self.userinfos:
            self.logger.debug('user %s not found', user)
            asyncio.ensure_future(self.update_userinfos())
            return default
        return self.userinfos[user]['name']

    async def update_channelinfos(self, channels=None):
        if channels is None:
            response = await self.api_call('channels.list')
            channels = response['channels']
        channelinfos = {}
        for c in channels:
            channelinfos[c['id']] = c
        self.conversations.update(channelinfos)

    def get_channelgroupname(self, channel, default=None):
        if channel.startswith('C'):
            return self.get_channelname(channel, default)
        if channel.startswith('G'):
            return self.get_groupname(channel, default)
        if channel.startswith('D'):
            return 'DM'
        return default

    def get_channelname(self, channel, default=None):
        if channel not in self.conversations:
            self.logger.debug('channel %s not found', channel)
            asyncio.ensure_future(self.update_channelinfos())
            return default
        return self.conversations[channel]['name']

    async def update_groupinfos(self, groups=None):
        if groups is None:
            response = await self.api_call('groups.list')
            groups = response['groups']
        groupinfos = {}
        for c in groups:
            groupinfos[c['id']] = c
        self.conversations.update(groupinfos)

    def get_groupname(self, group, default=None):
        if group not in self.conversations:
            self.logger.debug('group %s not found')
            asyncio.ensure_future(self.update_groupinfos())
            return default
        return self.conversations[group]['name']

    def get_syncs(self, channelid=None, hangoutid=None):
        syncs = []
        for sync in self.syncs:
            if channelid == sync.channelid:
                syncs.append(sync)
            elif hangoutid == sync.hangoutid:
                syncs.append(sync)
        return syncs

    def matchReference(self, match):
        out = ""
        linktext = ""
        if match.group(5) == '|':
            linktext = match.group(6)
        if match.group(2) == '@':
            if linktext != "":
                out = linktext
            else:
                out = "@%s" % self.get_username(match.group(3), 'unknown:%s' % match.group(3))
        elif match.group(2) == '#':
            if linktext != "":
                out = "#%s" % linktext
            else:
                out = "#%s" % self.get_channelgroupname(match.group(3),
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
        elif filename_extension == ".jpe" and physical_extension in [ ".jpg", ".jpeg", ".jpe", ".jif", ".jfif" ]:
            # account for mimetypes idiosyncrancy to return jpe for valid jpeg
            pass
        else:
            self.logger.warning("unable to determine extension: {} {}".format(filename_extension, physical_extension))
            filename += filename_extension

        self.logger.info('uploading as %s', filename)
        image_id = yield from self.bot._client.upload_image(image_response, filename=filename)

        self.logger.info('sending HO message, image_id: %s', image_id)
        yield from sync._bridgeinstance._send_to_internal_chat(
            sync.hangoutid,
            "shared media from slack",
            {   "sync": sync,
                "source_user": username,
                "source_uid": userid,
                "source_title": channel_name },
            image_id=image_id )

    def config_syncto(self, channel, hangoutid, shortname):
        for sync in self.syncs:
            if sync.channelid == channel and sync.hangoutid == hangoutid:
                raise AlreadySyncingError

        sync = SlackRTMSync(self.bot, channel, hangoutid, shortname, self.get_teamname())
        sync.team_name = self.name # chatbridge needs this for context
        self.logger.info('adding sync: %s', sync.toDict())
        self.syncs.append(sync)
        syncs = _slackrtm_conversations_get(self.bot, self.name)
        self.logger.info('storing sync: %s', sync.toDict())
        syncs.append(sync.toDict())
        _slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_disconnect(self, channel, hangoutid):
        sync = None
        for s in self.syncs:
            if s.channelid == channel and s.hangoutid == hangoutid:
                sync = s
                self.logger.info('removing running sync: %s', s)
                s._bridgeinstance.close()
                self.syncs.remove(s)
        if not sync:
            raise NotSyncingError

        syncs = _slackrtm_conversations_get(self.bot, self.name)
        for s in syncs:
            if s['channelid'] == channel and s['hangoutid'] == hangoutid:
                self.logger.info('removing stored sync: %s', s)
                syncs.remove(s)
        _slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_setsyncjoinmsgs(self, channel, hangoutid, enable):
        sync = None
        for s in self.syncs:
            if s.channelid == channel and s.hangoutid == hangoutid:
                sync = s
        if not sync:
            raise NotSyncingError

        self.logger.info('setting sync_joins=%s for sync=%s', enable, sync.toDict())
        sync.sync_joins = enable

        syncs = _slackrtm_conversations_get(self.bot, self.name)
        for s in syncs:
            if s['channelid'] == channel and s['hangoutid'] == hangoutid:
                syncs.remove(s)
        self.logger.info('storing new sync=%s with changed sync_joins', s)
        syncs.append(sync.toDict())
        _slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_sethotag(self, channel, hangoutid, hotag):
        sync = None
        for s in self.syncs:
            if s.channelid == channel and s.hangoutid == hangoutid:
                sync = s
        if not sync:
            raise NotSyncingError

        self.logger.info('setting hotag="%s" for sync=%s', hotag, sync.toDict())
        sync.hotag = hotag

        syncs = _slackrtm_conversations_get(self.bot, self.name)
        for s in syncs:
            if s['channelid'] == channel and s['hangoutid'] == hangoutid:
                syncs.remove(s)
        self.logger.info('storing new sync=%s with changed hotag', s)
        syncs.append(sync.toDict())
        _slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_setimageupload(self, channel, hangoutid, upload):
        sync = None
        for s in self.syncs:
            if s.channelid == channel and s.hangoutid == hangoutid:
                sync = s
        if not sync:
            raise NotSyncingError

        self.logger.info('setting image_upload=%s for sync=%s', upload, sync.toDict())
        sync.image_upload = upload

        syncs = _slackrtm_conversations_get(self.bot, self.name)
        for s in syncs:
            if s['channelid'] == channel and s['hangoutid'] == hangoutid:
                syncs.remove(s)
        self.logger.info('storing new sync=%s with changed hotag', s)
        syncs.append(sync.toDict())
        _slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_setslacktag(self, channel, hangoutid, slacktag):
        sync = None
        for s in self.syncs:
            if s.channelid == channel and s.hangoutid == hangoutid:
                sync = s
        if not sync:
            raise NotSyncingError

        self.logger.info('setting slacktag="%s" for sync=%s', slacktag, sync.toDict())
        sync.slacktag = slacktag

        syncs = _slackrtm_conversations_get(self.bot, self.name)
        for s in syncs:
            if s['channelid'] == channel and s['hangoutid'] == hangoutid:
                syncs.remove(s)
        self.logger.info('storing new sync=%s with changed slacktag', s)
        syncs.append(sync.toDict())
        _slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_showslackrealnames(self, channel, hangoutid, realnames):
        sync = None
        for s in self.syncs:
            if s.channelid == channel and s.hangoutid == hangoutid:
                sync = s
        if not sync:
            raise NotSyncingError

        self.logger.info('setting showslackrealnames=%s for sync=%s', realnames, sync.toDict())
        sync.showslackrealnames = realnames

        syncs = _slackrtm_conversations_get(self.bot, self.name)
        for s in syncs:
            if s['channelid'] == channel and s['hangoutid'] == hangoutid:
                syncs.remove(s)
        self.logger.info('storing new sync=%s with changed hotag', s)
        syncs.append(sync.toDict())
        _slackrtm_conversations_set(self.bot, self.name, syncs)
        return

    def config_showhorealnames(self, channel, hangoutid, realnames):
        sync = None
        for s in self.syncs:
            if s.channelid == channel and s.hangoutid == hangoutid:
                sync = s
        if not sync:
            raise NotSyncingError

        self.logger.info('setting showhorealnames=%s for sync=%s', realnames, sync.toDict())
        sync.showhorealnames = realnames

        syncs = _slackrtm_conversations_get(self.bot, self.name)
        for s in syncs:
            if s['channelid'] == channel and s['hangoutid'] == hangoutid:
                syncs.remove(s)
        self.logger.info('storing new sync=%s with changed hotag', s)
        syncs.append(sync.toDict())
        _slackrtm_conversations_set(self.bot, self.name, syncs)
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

        try:
            msg = SlackMessage(self, reply)
        except (ParseError, IgnoreMessage) as err:
            self.logger.debug(repr(err))
            return
        except Exception as e:
            self.logger.exception('error parsing Slack reply: %s(%s)', type(e), str(e))
            return

        # commands can be processed even from unsynced channels
        try:
            await slackCommandHandler(self, msg)
        except IgnoreMessage:
            return
        except Exception as e:
            self.logger.exception('error in handleCommands: %s(%s)', type(e), str(e))

        syncs = self.get_syncs(channelid=msg.channel)
        if not syncs:
            # stop processing replies if no syncs are available (optimisation)
            return

        message = REFFMT.sub(self.matchReference, msg.text)
        message = slack_markdown_to_hangups(message)

        for sync in syncs:
            if not sync.sync_joins and msg.is_joinleave:
                continue

            if msg.from_ho_id != sync.hangoutid:
                username = msg.realname4ho if sync.showslackrealnames else msg.username4ho
                channel_name = self.get_channelgroupname(msg.channel)

                if msg.file_attachment:
                    if sync.image_upload:

                        asyncio.ensure_future(
                            self.upload_image(
                                msg.file_attachment,
                                sync,
                                username,
                                msg.user_id,
                                channel_name ))

                        self.lastimg = os.path.basename(msg.file_attachment)
                    else:
                        # we should not upload the images, so we have to send the url instead
                        message += msg.file_attachment

                asyncio.ensure_future(
                    sync._bridgeinstance._send_to_internal_chat(
                        sync.hangoutid,
                        message,
                        {   "sync": sync,
                            "source_user": username,
                            "source_uid": msg.user_id,
                            "source_gid": sync.channelid,
                            "source_title": channel_name }))

    async def _send_deferred_media(self, image_link, sync, full_name, link_names, photo_url, fragment):
        await self.api_call('chat.postMessage',
                      channel = sync.channelid,
                      text = "{} {}".format(image_link, fragment),
                      username = full_name,
                      link_names = True,
                      icon_url = photo_url)

    async def handle_ho_message(self, event, conv_id, channel_id):
        user = event.passthru["original_request"]["user"]
        message = event.passthru["original_request"]["message"]

        if not message:
            message = ""

        message = hangups_markdown_to_slack(message)

        """slackrtm uses an overengineered pseudo SlackRTMSync "structure" to contain individual 1-1 syncs
            we rely on the chatbridge to iterate through multiple syncs, and ensure we only have
            to deal with a single mapping at this level

            XXX: the mapping SHOULD BE single, but let duplicates get through"""

        active_syncs = []
        for sync in self.get_syncs(hangoutid=conv_id):
            if sync.channelid != channel_id:
                continue
            if sync.hangoutid != conv_id:
                continue
            active_syncs.append(sync)

        for sync in active_syncs:
            bridge_user = sync._bridgeinstance._get_user_details(user, { "event": event })

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

            """XXX: media sending:

            * if media link is already available, send it immediately
              * real events from google servers will have the medialink in event.conv_event.attachment
              * media link can also be added as part of the passthru
            * for events raised by other external chats, wait for the public link to become available
            """


            if "attachments" in event.passthru["original_request"] and event.passthru["original_request"]["attachments"]:
                # automatically prioritise incoming events with attachments available
                media_link = event.passthru["original_request"]["attachments"][0]
                self.logger.info("media link in original request: {}".format(media_link))

                message = "shared media: {}".format(media_link)

            elif isinstance(event, FakeEvent):
                if( "image_id" in event.passthru["original_request"]
                        and event.passthru["original_request"]["image_id"] ):
                    # without media link, create a deferred post until a public media link becomes available
                    image_id = event.passthru["original_request"]["image_id"]
                    self.logger.info("wait for media link: {}".format(image_id))

                    asyncio.ensure_future(
                        self.bot._handlers.image_uri_from(
                            image_id,
                            self._send_deferred_media,
                            sync,
                            display_name,
                            True,
                            bridge_user["photo_url"],
                            slackrtm_fragment ))

            elif( hasattr(event, "conv_event")
                    and hasattr(event.conv_event, "attachments")
                    and len(event.conv_event.attachments) == 1 ):
                # catch actual events with media link  but didn' go through the passthru
                media_link = event.conv_event.attachments[0]
                self.logger.info("media link in original event: {}".format(media_link))

                message = "shared media: {}".format(media_link)

            """standard message relay"""

            message = "{} {}".format(message, slackrtm_fragment)

            self.logger.info("message {}: {}".format(sync.channelid, message))
            await self.api_call('chat.postMessage',
                          channel = sync.channelid,
                          text = message,
                          username = display_name,
                          link_names = True,
                          icon_url = bridge_user["photo_url"])

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
            await self.api_call('chat.postMessage',
                          channel=sync.channelid,
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
            await self.api_call('chat.postMessage',
                          channel=sync.channelid,
                          text=message,
                          as_user=True,
                          link_names=True)

    def close(self):
        self.logger.debug("closing all bridge instances")
        for s in self.syncs:
            s._bridgeinstance.close()

        if self._session is not None:
            self._session.close()

    def __del__(self):
        self.close()

class SlackRTMThread():
    _listener = None
    def __init__(self, bot, config):
        self._bot = bot
        self._config = config

    async def run(self):
        logger.debug('SlackRTMThread.run()')

        try:
            if self._listener and self._listener in _slackrtms:
                self._listener.close()
                _slackrtms.remove(self._listener)
            self._listener = SlackRTM(self._bot, self._config)
            _slackrtms.append(self._listener)
            await self._listener.start()
        except asyncio.CancelledError:
            # close, nothing to do
            return
        except IncompleteLoginError:
            logger.error('IncompleteLoginError, restarting')
            await asyncio.sleep(1)
            return await self.run()
        except aiohttp.ClientError:
            logger.exception('Connection failed, waiting 10 sec for a restart')
            await asyncio.sleep(10)
            return await self.run()
        except Exception as err:
            logger.exception('SlackRTMThread: unhandled exception: %s', err)
        return

    def __del__(self):
        if self._listener and self._listener in _slackrtms:
            self._listener.close()
            _slackrtms.remove(self._listener)
