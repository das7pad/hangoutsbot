import html
import pprint
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


HOIDFMT = re.compile(r'^(.*) <ho://([^/]+)/([^|]+)\| >$',
                     re.MULTILINE | re.DOTALL)

GUCFMT = re.compile(r'^(.*)<(https?://[^\s/]*googleusercontent.com/[^\s]*)>$',
                    re.MULTILINE | re.DOTALL)

class SlackMessage(object):
    def __init__(self, slackrtm, reply):
        if reply['type'] in TYPES_TO_SKIP:
            raise IgnoreMessage('reply is not a "message": %s' % reply['type'])

        self.text = None
        self.user_id = None
        self.username = None
        self.username4ho = None
        self.realname4ho = None
        self.edited = None
        self.from_ho_id = None
        self.sender_id = None
        self.channel = None
        self.file_attachment = None

        text = u''
        username = ''
        edited = ''
        from_ho_id = ''
        sender_id = ''
        channel = None
        is_joinleave = False
        # only used during parsing
        user_id = ''
        is_bot = False

        if reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] == 'message_changed':
            if 'edited' in reply['message']:
                edited = '(Edited)'
                user_id = reply['message']['edited']['user']
                text = reply['message']['text']
            else:
                # sent images from HO got an additional message_changed subtype without an 'edited' when slack renders the preview
                if 'username' in reply['message']:
                    # we ignore them as we already got the (unedited) message
                    raise IgnoreMessage('ignore "edited" message from bot, possibly slack-added preview')
                else:
                    raise ParseError('strange edited message without "edited" member:\n%s' % str(reply))

        elif reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] == 'file_comment':
            user_id = reply['comment']['user']
            text = reply['text']

        elif reply['type'] == 'file_comment_added':
            user_id = reply['comment']['user']
            text = reply['comment']['comment']

        else:
            if reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] == 'bot_message' and 'user' not in reply:
                is_bot = True
                # this might be a HO relayed message, check if username is set and use it as username
                username = reply['username']

            elif 'text' not in reply or 'user' not in reply:
                raise ParseError('no text/user in reply:\n%s' % str(reply))

            else:
                user_id = reply['user']

            if 'text' not in reply or not len(reply['text']):
                # IFTTT?
                if 'attachments' in reply:
                    if 'text' in reply['attachments'][0]:
                        text = reply['attachments'][0]['text']
                    else:
                        raise ParseError('strange message without text in attachments:\n%s' % pprint.pformat(reply))
                    if 'fields' in reply['attachments'][0]:
                        for field in reply['attachments'][0]['fields']:
                            text += "\n*%s*\n%s" % (field['title'], field['value'])
                else:
                    raise ParseError('strange message without text and without attachments:\n%s' % pprint.pformat(reply))

            else:
                # dev: normal messages that are entered by a slack user usually go this route
                text = reply['text']

        file_attachment = None
        if 'file' in reply:
            if 'url_private_download' in reply['file']:
                file_attachment = reply['file']['url_private_download']

        # now we check if the message has the hidden ho relay tag, extract and remove it
        match = HOIDFMT.match(text)
        if match:
            text = match.group(1)
            from_ho_id = match.group(2)
            sender_id = match.group(3)
            if 'googleusercontent.com' in text:
                match = GUCFMT.match(text)
                if match:
                    text = match.group(1)
                    file_attachment = match.group(2)

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

        username4ho = username
        realname4ho = username
        if not is_bot:
            username = slackrtm.get_username(user_id, user_id)
            realname = slackrtm.get_realname(user_id, username)

            username4ho = u'{}'.format(username)
            realname4ho = u'{}'.format(realname)
        elif sender_id != '':
            username4ho = u'{}'.format(username)
            realname4ho = u'{}'.format(username)

        if 'channel' in reply:
            channel = reply['channel']
        elif 'group' in reply:
            channel = reply['group']
        if not channel:
            raise ParseError('no channel found in reply:\n%s' % pprint.pformat(reply))

        if reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] in ['channel_join', 'channel_leave', 'group_join', 'group_leave']:
            is_joinleave = True

        self.text = text
        self.user_id = user_id
        self.username = username
        self.username4ho = username4ho
        self.realname4ho = realname4ho
        self.edited = edited
        self.from_ho_id = from_ho_id
        self.sender_id = sender_id
        self.channel = channel
        self.file_attachment = file_attachment
        self.is_joinleave = is_joinleave
