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

        self.text = ''
        self.user = None
        self.user_id = None
        self.username = None
        self.edited = False
        self.segments = None
        self.file_attachment = None

        self.subtype = (reply.get('subtype')
                        if reply['type'] == 'message' else None)

        self.set_raw_content(reply)

        if 'file' in reply:
            if reply.get('upload') is False:
                raise IgnoreMessage('already seen this image')

            self.file_attachment = reply['file']['url_private_download']
            lines = []
            lines.append(reply['file'].get('title', ''))
            lines.append(
                ('> ' + reply['file']['initial_comment'].get('comment', ''))
                if 'initial_comment' in reply['file'] else '')
            # if no title or comment are given, use the default text as fallback
            self.text = '\n'.join(lines).strip() or self.text

        if not self.segments:
            self.segments, image_url = parse_text(slackrtm, self.text)
            self.file_attachment = image_url or self.file_attachment

        if self.subtype in TYPES_MEMBERSHIP_JOIN:
            self.is_joinleave = 1
            if 'inviter' in reply:
                self.user = SlackUser(slackrtm, user_id=reply['inviter'],
                                      channel=self.channel)
                self.participant_user = [SlackUser(slackrtm,
                                                   user_id=self.user_id,
                                                   channel=self.channel)]

        elif self.subtype in TYPES_MEMBERSHIP_LEAVE:
            self.is_joinleave = 2

        else:
            self.is_joinleave = None

        if self.user is None:
            self.user = SlackUser(slackrtm, user_id=self.user_id,
                                  name=self.username, channel=self.channel)
            self.participant_user = []

        self.title = slackrtm.get_chatname(self.channel, '')
        self.username = self.user.username
        self.text = get_formatted(self.segments, 'text')

    def set_raw_content(self, reply):
        """set the message text and try to fetch a user (id) or set a username

        Args:
            reply (dict): slack response

        Raises:
            IgnoreMessage: the message should not be synced
            ParseError: the message content could not be parsed
        """
        subtype = self.subtype
        if subtype == 'message_changed':
            if 'edited' not in reply['message']:
                raise IgnoreMessage('not a user message')

            self.edited = True
            self.user_id = reply['message']['edited'].get('user')
            self.text = str(reply['message'].get('text'))

        elif subtype == 'file_comment':
            self.user_id = reply['comment']['user']
            self.text = reply['text']

        elif reply['type'] == 'file_comment_added':
            self.user_id = reply['comment']['user']
            self.text = reply['comment']['comment']

        elif subtype == 'bot_message':
            self.parse_bot_message(reply)

        else:
            # set user
            if 'user' not in reply and 'username' not in reply:
                raise IgnoreMessage('not a user message')

            self.username = reply.get('username')
            self.user_id = reply.get('user')

            # set text
            if 'text' in reply and reply['text']:
                self.text = reply['text']

            elif 'attachments' in reply:
                attachment = reply['attachments'][0]
                if 'text' not in attachment:
                    raise ParseError('message without text in attachment')
                lines = [attachment['text']]
                if 'fields' in attachment:
                    for field in attachment['fields']:
                        lines.append('*%s*' % field['title'])
                        lines.append('%s' % field['value'])
                self.text = '\n'.join(lines)

    def parse_bot_message(self, reply):
        """parse bot messages from various services

        add custom parsing here

        Args:
            reply (dict): slack response

        Raises:
            IgnoreMessage: the message should not be synced
        """
        # pylint: disable=no-self-use
        raise IgnoreMessage('unknown service: %s' % reply)
