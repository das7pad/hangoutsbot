"""Slack RTM response parser"""

import html
import re

import emoji

from sync.parser import get_formatted

from .exceptions import (
    IgnoreMessage,
    ParseError,
)
from .parsers import SlackMessageSegment
from .user import SlackUser

# fix for simple_smile support
emoji.EMOJI_UNICODE[':simple_smile:'] = emoji.EMOJI_UNICODE[':smiling_face:']
emoji.EMOJI_ALIAS_UNICODE[':simple_smile:'] = (
    emoji.EMOJI_UNICODE[':smiling_face:'])

TYPES_TO_SKIP = (
    'file_created', 'file_shared', 'file_public', 'file_change',
    'file_comment_added', 'file_comment_deleted', 'file_comment_edited',
    'message_deleted',
)

TYPES_MEMBERSHIP_JOIN = ('channel_join', 'group_join')
TYPES_MEMBERSHIP_LEAVE = ('channel_leave', 'group_leave')

GUCFMT = re.compile(r'^(.*)<(https?://[^\s/]*googleusercontent.com/[^\s]*)>$',
                    re.MULTILINE | re.DOTALL)

REFFMT = re.compile(r'<((.)([^|>]*))((\|)([^>]*)|([^>]*))>')

def parse_text(slackrtm, text):
    """clean the text from slack tags/markdown and search for an image

    Args:
        slackrtm (core.SlackRTM): a running instance
        text (str): raw message from slack

    Returns:
        tuple: `(<list>, <str>)`, a list of `parsers.SlackMessageSegment`s - the
            formatted text; the str: an image url - if present otherwise None
    """
    def matchreference(match):
        """replace slack tags with the full descriptor

        Args:
            match (_sre.SRE_Match): regex Match Object

        Returns:
            str: the item to display
        """
        out = ""
        linktext = ""
        if match.group(5) == '|':
            linktext = match.group(6)
        if match.group(2) == '@':
            if linktext != "":
                out = linktext
            else:
                out = "@%s" % slackrtm.get_username(
                    match.group(3), 'unknown:%s' % match.group(3))
        elif match.group(2) == '#':
            if linktext != "":
                out = "#%s" % linktext
            else:
                out = "#%s" % slackrtm.get_chatname(
                    match.group(3), 'unknown:%s' % match.group(3))
        else:
            linktarget = match.group(1)
            # save '<text>'
            out = ('<%s|%s>' % (linktarget, linktext) if linktext else
                   '<%s|%s>' % (linktarget, linktarget) if 'http' in linktarget
                   else '<%s>' % linktarget)
        out = out.replace('_', '%5F')
        out = out.replace('*', '%2A')
        out = out.replace('`', '%60')
        return out


    if not text:
        # performance
        return [], None

    image_url = None
    if 'googleusercontent.com' in text:
        match = GUCFMT.match(text)
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
    text = re.sub(r"::skin-tone-\d:", ":", text, flags=re.IGNORECASE)

    # convert emoji aliases into their unicode counterparts
    text = emoji.emojize(text, use_aliases=True)

    text = REFFMT.sub(matchreference, text)
    segments = SlackMessageSegment.from_str(text)
    return segments, image_url


class SlackMessage(object):
    """parse the response from slack to form a message for syncing

    Args:
        slackrtm (core.SlackRTM): the instance which received the message
        reply (dict): response from slack

    Raises:
        IgnoreMessage: the message should not be synced
        ParseError: the message content could not be parsed
    """
    def __init__(self, slackrtm, reply):
        if reply['type'] in TYPES_TO_SKIP:
            raise IgnoreMessage('reply is not a "message": %s' % reply['type'])

        self.channel = reply.get('channel') or reply.get('group')
        if self.channel is None:
            raise ParseError('no channel found in reply')

        self.user = None
        self.edited = False
        self.segments = []
        self.image = None

        subtype = reply.get('subtype')

        self.set_base(slackrtm, reply)

        # membership part
        self.participant_user = []
        if subtype in TYPES_MEMBERSHIP_JOIN:
            self.is_joinleave = 1
            if 'inviter' in reply:
                self.participant_user.append(self.user)
                self.user = SlackUser(slackrtm, user_id=reply['inviter'],
                                      channel=self.channel)
        elif subtype in TYPES_MEMBERSHIP_LEAVE:
            self.is_joinleave = 2
        else:
            self.is_joinleave = None

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

        elif subtype == 'file_comment':
            user_id = reply['comment']['user']
            text = reply['text']

        elif reply['type'] == 'file_comment_added':
            user_id = reply['comment']['user']
            text = reply['comment']['comment']

        elif subtype == 'bot_message':
            self.parse_bot_message(slackrtm, reply)
            return

        else:
            # set user
            if 'user' not in reply:
                raise IgnoreMessage('not a user message')

            user_id = reply['user']

            # set text
            if 'file' in reply:
                if reply.get('upload') is False:
                    raise IgnoreMessage('already seen this image')

                file = reply['file']
                file_attachment = file['url_private_download']
                text = file.get('title', '')
                text += ('\n> ' + file['initial_comment']['comment']
                         if ('initial_comment' in file
                             and 'comment' in file['initial_comment']) else '')
                # no title and no comment -> use the default text as fallback
                text = text.strip() or reply.get('text')

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
            headers={'Authorization': 'Bearer ' + slackrtm.apikey})

    def parse_bot_message(self, slackrtm, reply):
        """parse bot messages from various services

        add custom parsing here:
        - required:
            `self.segments` (list), a list of `parsers.SlackMessageSegment`
            `self.user` (user.SlackUser), the sender
        - optional:
            `self.image` (sync.image.SyncImage), attached media
            `self.edited` (bool), edited version of a previous message

        Args:
            slackrtm (core.SlackRTM): the instance which received the `reply`
            reply (dict): slack response

        Raises:
            IgnoreMessage: the message should not be synced
        """
        # pylint: disable=no-self-use, unused-argument
        raise IgnoreMessage('unknown service')
