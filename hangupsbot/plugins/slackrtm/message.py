"""Slack RTM response parser"""

import html
import re

import emoji

from hangupsbot.base_models import BotMixin
from hangupsbot.sync.event import SyncReply
from hangupsbot.sync.parser import get_formatted

from .constants import (
    MESSAGE_TYPES_TO_SKIP,
    MESSAGE_SUBTYPES_MEMBERSHIP_JOIN,
    MESSAGE_SUBTYPES_MEMBERSHIP_LEAVE,
)
from .exceptions import (
    IgnoreMessage,
    ParseError,
    SlackAPIError,
)
from .parsers import SlackMessageSegment
from .user import SlackUser

# fix for simple_smile support
emoji.EMOJI_UNICODE[':simple_smile:'] = emoji.EMOJI_UNICODE[':smiling_face:']
emoji.EMOJI_ALIAS_UNICODE[':simple_smile:'] = (
    emoji.EMOJI_UNICODE[':smiling_face:'])

GUC_FMT = re.compile(r'^(.*)<(https?://[^\s/]*googleusercontent.com/[^\s]*)>$',
                     re.MULTILINE | re.DOTALL)

REF_FMT = re.compile(r'<((.)([^|>]*))((\|)([^>]*)|([^>]*))>')

def parse_text(slackrtm, text):
    """clean the text from slack tags/markdown and search for an image

    Args:
        slackrtm (core.SlackRTM): a running instance
        text (str): raw message from slack

    Returns:
        tuple[list[parsers.SlackMessageSegment], str]: formatted text and an
            image url - if present otherwise None
    """
    def matchreference(match):
        """replace slack tags with the full descriptor

        Args:
            match (_sre.SRE_Match): regex Match Object

        Returns:
            str: the item to display
        """
        link_text = ''
        if match.group(5) == '|':
            link_text = match.group(6)
        if match.group(2) == '@':
            if link_text != '':
                out = link_text
            else:
                out = '@%s' % slackrtm.get_username(
                    match.group(3), 'unknown:%s' % match.group(3))
        elif match.group(2) == '#':
            if link_text != '':
                out = '#%s' % link_text
            else:
                out = '#%s' % slackrtm.get_chatname(
                    match.group(3), 'unknown:%s' % match.group(3))
        else:
            link_target = match.group(1)
            # save '<text>'
            out = ('<%s|%s>' % (link_target, link_text) if link_text else
                   '<%s>' % link_target if 'http' not in link_target
                   else '<%s|%s>' % (link_target, link_target))
        out = out.replace('_', '%5F')
        out = out.replace('*', '%2A')
        out = out.replace('`', '%60')
        return out


    if not text:
        # performance
        return [], None

    image_url = None
    if 'googleusercontent.com' in text:
        match = GUC_FMT.match(text)
        if match:
            image_url = match.group(2)
            text = match.group(1).replace(image_url, '')

    text = html.unescape(text)

    # Note:
    # strip :skin-tone-<id>:
    # * depends on the slack users emoji style,
    #       e.g. hangouts style has no skin tone support
    # * do it BEFORE emojize() for more reliable detection of sub-pattern
    #       :some_emoji(::skin-tone-\d:)
    text = re.sub(r'::skin-tone-\d:', ':', text, flags=re.IGNORECASE)

    # convert emoji aliases into their unicode counterparts
    text = emoji.emojize(text, use_aliases=True)

    text = REF_FMT.sub(matchreference, text)
    segments = SlackMessageSegment.from_str(text)
    return segments, image_url


class SlackMessage(BotMixin):
    """parse the response from slack to form a message for syncing

    Args:
        slackrtm (core.SlackRTM): the instance which received the message
        reply (dict): response from slack

    Raises:
        IgnoreMessage: the message should not be synced
        ParseError: the message content could not be parsed
    """
    _last_messages = {}

    def __init__(self, slackrtm, reply):
        if reply['type'] in MESSAGE_TYPES_TO_SKIP:
            raise IgnoreMessage('reply is not a "message": %s' % reply['type'])

        self.channel = reply.get('channel') or reply.get('group')
        if not isinstance(self.channel, str):
            raise ParseError('no channel found in reply')

        self.user = None
        self.edited = False
        self.segments = []
        self.image = None

        subtype = reply.get('subtype')

        self.set_base(slackrtm, reply)

        # membership part
        self.participant_user = []
        if subtype in MESSAGE_SUBTYPES_MEMBERSHIP_JOIN:
            self.is_join_leave = 1
            if 'inviter' in reply:
                self.participant_user.append(self.user)
                self.user = SlackUser(slackrtm, user_id=reply['inviter'],
                                      channel=self.channel)
        elif subtype in MESSAGE_SUBTYPES_MEMBERSHIP_LEAVE:
            self.is_join_leave = 2
        else:
            self.is_join_leave = None

    @property
    def text(self):
        """get the raw text without formatting

        Returns:
            str: the raw message content
        """
        return get_formatted(self.segments, 'text')

    def set_base(self, slackrtm, reply):
        """set the message text, user and media

        Args:
            slackrtm (core.SlackRTM): the instance which received the `reply`
            reply (dict): slack response

        Raises:
            IgnoreMessage: the message should not be synced
            ParseError: the message content could not be parsed
        """
        subtype = reply.get('subtype')
        text = None
        file_attachment = None
        if subtype == 'message_changed':
            if 'edited' not in reply['message']:
                raise IgnoreMessage('not a user message')

            self.edited = True
            user_id = reply['message']['edited'].get('user')
            text = str(reply['message'].get('text'))

        elif subtype == 'bot_message':
            self.parse_bot_message(slackrtm, reply)
            return

        else:
            # set user
            if 'user' not in reply and 'comment' not in reply:
                raise IgnoreMessage('not a user message')

            user_id = (reply['user'] if 'user' in reply
                       else reply['comment']['user'])

            # set text
            if 'files' in reply:
                if reply.get('upload') is False:
                    raise IgnoreMessage('already seen this image')

                file = reply['files'][0]
                file_attachment = file['url_private_download']
                # file caption -> file title
                text = reply.get('text') or file.get('title', '')

            elif 'text' in reply and reply['text']:
                text = reply['text']

            elif 'attachments' in reply:
                attachment = reply['attachments'][0]
                lines = [attachment['text']] if 'text' in attachment else []
                for field in attachment.get('fields', ()):
                    lines.append('*%s*' % field['title'])
                    lines.append('%s' % field['value'])
                text = '\n'.join(lines)

        self.user = SlackUser(slackrtm, user_id=user_id,
                              name=reply.get('username'),
                              channel=self.channel)
        self.segments, image_url = parse_text(slackrtm, text)

        # set media
        image_url = image_url or file_attachment
        self.image = slackrtm.bot.sync.get_sync_image(
            url=image_url,
            headers={'Authorization': 'Bearer ' + slackrtm.api_key})

    @classmethod
    def track_message(cls, bot, channel_tag, reply):
        """add a message id to the last message and delete old items

        Args:
            bot (hangupsbot.core.HangupsBot): the running instance
            channel_tag (str): identifier for a channel of a slack team
            reply (dict): message response from slack
        """
        timestamp = reply.get('ts') or 0
        messages = cls._last_messages.setdefault(channel_tag, [])

        messages.append(int(float(timestamp)))
        messages.sort(reverse=True)
        for i in range(2 * bot.config['sync_reply_spam_offset'],
                       len(messages)):
            messages.pop(i)

    async def get_sync_reply(self, slackrtm, reply):
        """get the 'real' reply to a message or thread

        Args:
            slackrtm (core.SlackRTM): the instance which received the `reply`
            reply (dict): message response from slack

        Returns:
            hangupsbot.sync.event.SyncReply: the wrapped reply content or `None`
        """
        if (reply['type'] == 'message' and 'text' in reply
                and reply.get('attachments')    # covers missing/empty
                and reply['attachments'][0].get('is_share')
                and 'text' in reply['attachments'][0]):

            timestamp = reply['attachments'][0].get('ts') or 0

            segments, image_url = parse_text(slackrtm,
                                             reply['attachments'][0]['text'])
            r_text = get_formatted(segments, 'text')

            if image_url is None:
                image = None
            else:
                image = slackrtm.bot.sync.get_sync_image(url=image_url)

            # the `author_subname` could include the synced source title
            r_user = SlackUser(
                slackrtm, channel=self.channel,
                name=reply['attachments'][0].get('author_name'),
                nickname=reply['attachments'][0].get('author_subname'))

        elif ('attachments' in reply and reply['attachments'][0].get('is_share')
              and 'from_url' in reply['attachments'][0]):
            # query needed
            timestamp = reply['attachments'][0]['from_url'].rsplit('p', 1)[-1]
            method = ('channels.history' if self.channel[0] == 'C' else
                      'groups.history' if self.channel[0] == 'G' else
                      'im.history')
            try:
                resp = await slackrtm.api_call(
                    method,
                    channel=self.channel,
                    latest=float(timestamp) / 1000000,
                    inclusive=True, count=1)
            except SlackAPIError as err:
                slackrtm.logger.error(
                    'failed to get a history item via %r, age: %s: %r',
                    method, timestamp, err
                )
                return None

            if not resp.get('messages'):
                return None
            try:
                # Slack does not send the `channel` again
                resp['messages'][0]['channel'] = self.channel

                old_msg = SlackMessage(slackrtm, resp['messages'][0])
            except (KeyError, IndexError, IgnoreMessage, ParseError):
                # covers invalid api-responses and intended Exceptions
                slackrtm.logger.debug(
                    'discard reply: %r',
                    resp['messages'][0],
                    exc_info=True
                )
                return None
            image = old_msg.image
            r_text = old_msg.text
            r_user = old_msg.user
        else:
            return None

        channel_tag = '%s:%s' % (slackrtm.identifier, self.channel)
        messages = self._last_messages.get(channel_tag)
        try:
            offset = messages.index(int(float(timestamp)))
        except ValueError:
            messages.append(int(float(timestamp)))
            offset = None

        return SyncReply(identifier=channel_tag, user=r_user, text=r_text,
                         image=image, offset=offset)

    def parse_bot_message(self, slackrtm, reply):
        """parse bot messages from various services

        add custom parsing here:
        - required:
            `self.segments` (list), a list of `parsers.SlackMessageSegment`
            `self.user` (user.SlackUser), the sender
        - optional:
            `self.image` (hangupsbot.sync.image.SyncImage), attached media
            `self.edited` (bool), edited version of a previous message

        Args:
            slackrtm (core.SlackRTM): the instance which received the `reply`
            reply (dict): slack response

        Raises:
            IgnoreMessage: the message should not be synced
        """
        # pylint: disable=no-self-use, unused-argument
        raise IgnoreMessage('unknown service')
