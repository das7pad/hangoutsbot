"""telepot message wrapper"""
__author__ = 'das7pad@outlook.com'

import logging

import telepot

from hangupsbot.base_models import BotMixin
from hangupsbot.sync.event import SyncReply
from hangupsbot.sync.user import SyncUser
from hangupsbot.utils.cache import Cache
from .exceptions import IgnoreMessage
from .user import User


logger = logging.getLogger(__name__)


class _LocationCache(Cache):
    """cache for location data

    keys: msg_id (str)
    values: last location data (tuple):
        `(<timestamp (int)>, (<pos_lat (int)>, <pos_lng (int)>))`

    Note: we can not resolve a msg_id to a user_id without storing the original
     message. The debug-mode logs complete messages.
    """

    def __missing__(self, identifier):
        return 0, (0, 0)


_LOCATION_SHARING_MAX = 60 * 60 * 8  # 8hours
_LOCATION_CACHE = _LocationCache(
    default_timeout=_LOCATION_SHARING_MAX,
    name='telesync_location_cache',
    increase_on_access=False)
_LOCATION_CACHE.start()


class Message(dict, BotMixin):
    """parse the message once

    keep value accessing via dict

    Args:
        msg (dict): Message object from Telegram

    Raises:
        IgnoreMessage: the message should not be synced
    """
    tg_bot = None
    _last_messages = {}

    def __init__(self, msg):
        super().__init__(msg)
        self.content_type, self.chat_type, chat_id = telepot.glance(msg)
        self.chat_id = str(chat_id)
        self.reply = (Message(msg['reply_to_message'])
                      if 'reply_to_message' in msg else None)
        self.user = User(self.tg_bot, msg)
        self.image_info = None
        self._set_content()
        self.add_message(self.bot, chat_id, self['message_id'])

        base_path = ['telesync', 'chat_data', self.chat_id]

        if self.user.usr_id != '0':
            # list valid users in the chats users only
            user_path = base_path + ['user', self.user.usr_id]
            self.bot.memory.set_by_path(user_path, 1)
        else:
            self.bot.memory.ensure_path(base_path)

        self.bot.memory.get_by_path(base_path).update(msg['chat'])

    @property
    def edited(self):
        """Check whether the message is an update of a previous message

        Returns:
            bool: True if the message is an update, otherwise False
        """
        return 'edit_date' in self

    @property
    def msg_id(self):
        """get the message identifier

        Returns:
            str: the unique identifier of the message
        """
        return str(self['message_id'])

    @classmethod
    def add_message(cls, bot, chat_id, msg_id):
        """add a message id to the last message and delete old items

        Args:
            bot (hangupsbot.core.HangupsBot): the running instance
            chat_id (int): identifier for a chat
            msg_id (int): int or string, the unique id of the message
        """
        if chat_id in cls._last_messages:
            messages = cls._last_messages[chat_id]
        else:
            messages = cls._last_messages[chat_id] = []

        messages.append(int(msg_id or 0))
        messages.sort(reverse=True)
        for i in range(2 * bot.config['sync_reply_spam_offset'],
                       len(messages)):
            messages.pop(i)

    def get_group_name(self):
        """get a configured chat title or the current title of the chat

        Returns:
            string: chat title of group/super/channel, or None
        """
        if self.chat_type in ['group', 'supergroup', 'channel']:
            name = self['chat']['title']
        else:
            name = _('DM - {}').format(self.user.full_name)
        # save the name but do not dump the memory explicit
        self.bot.memory.set_by_path(
            ['telesync', 'chat_data', self.chat_id, 'name'], name)
        return name

    async def get_reply(self):
        """check the reply for a hidden synced user and create the image

        Returns:
            SyncReply: content wrapper with the user, text and image
        """
        if self.reply is None:
            return None
        separator = self.bot.config['sync_separator']
        if self.chat_type == 'channel':
            # do not display a user name
            self.reply.user.is_self = True
            user = self.reply.user
            text = self.reply.text
        elif (self.reply.user.usr_id == self.tg_bot.user.usr_id and
              separator in self.reply.text):
            # reply message has been synced, extract the user and text
            r_user, text = self.reply.text.split(separator, 1)
            # might be a reply as well
            r_user = r_user.rsplit('\n', 1)[-1]
            user = SyncUser(identifier='telesync', user_name=r_user)
        else:
            user = self.reply.user
            text = self.reply.text

        if self.reply.image_info is not None:
            image = await self.tg_bot.get_image(*self.reply.image_info)
        else:
            image = None

        try:
            offset = self._last_messages[int(self.chat_id)].index(
                int(self.reply.msg_id))
        except ValueError:
            offset = None

        return SyncReply(identifier='telesync', user=user, text=text,
                         offset=offset, image=image)

    def _set_content(self):
        """map content type to a proper message text and find images

        Raises:
            IgnoreMessage: the message should not be synced,
                invalid type or duplicate location
        """

        def _create_google_maps_url():
            """create Google Maps query from a location in the message

            Returns:
                str: a google maps link or .content_type or error

            Raises:
                IgnoreMessage: duplicate location, discard this message
            """
            msg_id = self.msg_id  # cache property call
            pos = (self['location']['latitude'], self['location']['longitude'])
            if self.edited:
                # the message is part of a live location sharing

                last_synced, last_pos = _LOCATION_CACHE.get(msg_id, pop=True)
                last_synced = last_synced or self['date']
                if last_pos == pos:
                    prefix = _('Last live update: ')
                else:
                    prefix = _('Live update: ')
                    _LOCATION_CACHE.add(msg_id, (self['edit_date'], pos))

                    min_delay = self.tg_bot.config(
                        'location_sharing_update_delay')
                    if self['edit_date'] - last_synced < min_delay:
                        raise IgnoreMessage()

                if self.tg_bot.config('location_sharing_remove_edit_tag'):
                    self.pop('edit_date')
            else:
                prefix = ''

            return '{prefix}https://maps.google.com/maps?q={lat},{lng}'.format(
                prefix=prefix, lat=pos[0], lng=pos[1])

        if self.content_type == 'text':
            self.text = self['text']
            return

        if self.content_type == 'photo':
            self.text = self.get('caption', '')
            sorted_photos = sorted(self['photo'], key=lambda k: k['width'])
            self.image_info = sorted_photos[- 1], 'photo'

        elif self.content_type == 'sticker':
            self.text = self["sticker"].get('emoji')
            self.image_info = self['sticker'], 'sticker'

        elif (self.content_type == 'document' and
              self['document'].get('mime_type') == 'video/mp4'
              and self['document'].get('file_size', 0) < 10000000):
            self.text = self.get('caption', '')
            self.image_info = self['document'], 'gif'

        elif (self.content_type == 'document' and
              self['document'].get('mime_type', '').startswith(('image/',
                                                                'video/'))):
            self.text = self.get('caption', '')
            extension = (self['document'].get('file_name') or
                         self['document']['mime_type']
                         ).rsplit('.', 1)[-1].rsplit('/', 1)[-1]

            type_ = ('photo' if 'image' in self['document']['mime_type']
                     else 'video')
            self.image_info = self['document'], type_, extension

        elif self.content_type == 'video':
            self.text = ''
            self.image_info = self['video'], 'video'

        elif self.content_type == 'location':
            self.text = _create_google_maps_url()

        elif self.content_type not in ('new_chat_member', 'new_chat_members',
                                       'left_chat_member'):
            raise IgnoreMessage()
