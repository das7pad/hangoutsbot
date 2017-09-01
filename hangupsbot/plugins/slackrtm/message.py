import html
import pprint
import re

import emoji

from .exceptions import ParseError

class SlackMessage(object):
    def __init__(self, slackrtm, reply):
        self.text = None
        self.user = None
        self.username = None
        self.username4ho = None
        self.realname4ho = None
        self.tag_from_slack = None
        self.edited = None
        self.from_ho_id = None
        self.sender_id = None
        self.channel = None
        self.file_attachment = None

        if 'type' not in reply:
            raise ParseError('no "type" in reply: %s' % str(reply))

        if reply['type'] in [ 'pong', 'presence_change', 'user_typing', 'file_shared', 'file_public',
                              'file_comment_added', 'file_comment_deleted', 'message_deleted', 'file_created' ]:

            raise ParseError('not a "message" type reply: type=%s' % reply['type'])

        text = u''
        username = ''
        edited = ''
        from_ho_id = ''
        sender_id = ''
        channel = None
        is_joinleave = False
        # only used during parsing
        user = ''
        is_bot = False

        if reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] == 'message_changed':
            if 'edited' in reply['message']:
                edited = '(Edited)'
                user = reply['message']['edited']['user']
                text = reply['message']['text']
            else:
                # sent images from HO got an additional message_changed subtype without an 'edited' when slack renders the preview
                if 'username' in reply['message']:
                    # we ignore them as we already got the (unedited) message
                    raise ParseError('ignore "edited" message from bot, possibly slack-added preview')
                else:
                    raise ParseError('strange edited message without "edited" member:\n%s' % str(reply))

        elif reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] == 'file_comment':
            user = reply['comment']['user']
            text = reply['text']

        elif reply['type'] == 'file_comment_added':
            user = reply['comment']['user']
            text = reply['comment']['comment']

        else:
            if reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] == 'bot_message' and 'user' not in reply:
                is_bot = True
                # this might be a HO relayed message, check if username is set and use it as username
                username = reply['username']

            elif 'text' not in reply or 'user' not in reply:
                raise ParseError('no text/user in reply:\n%s' % str(reply))

            else:
                user = reply['user']

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
        hoidfmt = re.compile(r'^(.*) <ho://([^/]+)/([^|]+)\| >$', re.MULTILINE | re.DOTALL)
        match = hoidfmt.match(text)
        if match:
            text = match.group(1)
            from_ho_id = match.group(2)
            sender_id = match.group(3)
            if 'googleusercontent.com' in text:
                gucfmt = re.compile(r'^(.*)<(https?://[^\s/]*googleusercontent.com/[^\s]*)>$', re.MULTILINE | re.DOTALL)
                match = gucfmt.match(text)
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
        tag_from_slack = False # XXX: prevents key not defined on unmonitored channels
        if not is_bot:
            domain = slackrtm.get_slack_domain()
            username = slackrtm.get_username(user, user)
            realname = slackrtm.get_realname(user,username)

            username4ho = u'{}'.format(username)
            realname4ho = u'{}'.format(realname)
            tag_from_slack = True
        elif sender_id != '':
            username4ho = u'{}'.format(username)
            realname4ho = u'{}'.format(username)
            tag_from_slack = False

        if 'channel' in reply:
            channel = reply['channel']
        elif 'group' in reply:
            channel = reply['group']
        if not channel:
            raise ParseError('no channel found in reply:\n%s' % pprint.pformat(reply))

        if reply['type'] == 'message' and 'subtype' in reply and reply['subtype'] in ['channel_join', 'channel_leave', 'group_join', 'group_leave']:
            is_joinleave = True

        self.text = text
        self.user = user
        self.username = username
        self.username4ho = username4ho
        self.realname4ho = realname4ho
        self.tag_from_slack = tag_from_slack
        self.edited = edited
        self.from_ho_id = from_ho_id
        self.sender_id = sender_id
        self.channel = channel
        self.file_attachment = file_attachment
        self.is_joinleave = is_joinleave
