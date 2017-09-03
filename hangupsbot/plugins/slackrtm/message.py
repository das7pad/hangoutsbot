import html
import re

import emoji

from .exceptions import (
    IgnoreMessage,
    ParseError,
)

TYPES_TO_SKIP = (
    'file_created', 'file_shared', 'file_public', 'file_change',
    'file_comment_added', 'file_comment_deleted', 'file_comment_edited',
    'message_deleted', 'presence_change', 'user_typing', 'pong'
)

TYPES_MEMBERSHIP_CHANGE = ('channel_join', 'channel_leave',
                           'group_join', 'group_leave')

HOIDFMT = re.compile(r'^(.*) <ho://([^/]+)/([^|]+)\| >$',
                     re.MULTILINE | re.DOTALL)

GUCFMT = re.compile(r'^(.*)<(https?://[^\s/]*googleusercontent.com/[^\s]*)>$',
                    re.MULTILINE | re.DOTALL)

class SlackMessage(object):
    def __init__(self, slackrtm, reply):
        if reply['type'] in TYPES_TO_SKIP:
            raise IgnoreMessage('reply is not a "message": %s' % reply['type'])

        self.channel = reply.get('channel') or reply.get('group')
        if self.channel is None:
            raise ParseError('no channel found in reply')

        self.text = None
        self.user_id = None
        self.username = None
        self.edited = False
        self.from_ho_id = None
        self.file_attachment = None

        self.subtype = (reply.get('subtype')
                        if reply['type'] == 'message' else None)

        self.set_raw_content(reply)
        text = self.text

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
            text = '\n'.join(lines).strip() or text

        # now we check if the message has the hidden ho relay tag, extract and remove it
        match = HOIDFMT.match(text)
        if match:
            text = match.group(1)
            self.from_ho_id = match.group(2)
            if 'googleusercontent.com' in text:
                match = GUCFMT.match(text)
                if match:
                    text = match.group(1)
                    self.file_attachment = match.group(2)

        # text now contains the real message, but html entities have to be dequoted still
        text = html.unescape(text)

        """
        strip :skin-tone-<id>: if present and apparently combined with an actual emoji alias
        * depends on the slack users emoji style, e.g. hangouts style has no skin tone support
        * do it BEFORE emojize() for more reliable detection of sub-pattern :some_emoji(::skin-tone-\d:)
        """
        text = re.sub(r"::skin-tone-\d:", ":", text, flags=re.IGNORECASE)

        # convert emoji aliases into their unicode counterparts
        text = emoji.emojize(text, use_aliases=True)


        if self.user_id is not None:
            self.username = slackrtm.get_username(self.user_id,
                                                  self.user_id)
            realname4ho = slackrtm.get_realname(self.user_id, self.username)
        else:
            realname4ho = self.username

        self.is_joinleave = self.subtype in TYPES_MEMBERSHIP_CHANGE

        self.text = text
        self.username4ho = self.username
        self.realname4ho = realname4ho

    def set_raw_content(self, reply):
        """set the message text and try to fetch a user (id) or set a username

        Args:
            reply: dict, slack response
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
            reply: dict, slack response
        """
        # pylint: disable=no-self-use
        raise IgnoreMessage('unknown service: %s' % reply)
