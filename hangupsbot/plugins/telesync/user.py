"""Telegram user from message dict

{'id': int, 'first_name': string, 'last_name': string, 'username': string}
"""
__author__ = 'das7pad@outlook.com'

import logging

import telepot.exception

from hangupsbot.sync.user import SyncUser

logger = logging.getLogger(__name__)

class User(SyncUser):
    """init a user base on a telegram user object in a message object

    Args:
        tg_bot: TelegramBot instance
        msg: Message instance or message dict
        chat_action: target to pick user from, is key in msg
        gpluslink: boolean, set to True to get G+links instead of t.me links
    """
    # Fallback for Telegram-channel with redacted publishers
    FALLBACK = {'id': 0, 'first_name': '~'}
    __slots__ = ('tg_bot', 'usr_id', 'full_name', 'username',
                 'photo_url', 'is_self')

    def __init__(self, tg_bot, msg, chat_action='from', gpluslink=False):
        self.tg_bot = tg_bot
        if chat_action not in msg:
            msg[chat_action] = self.FALLBACK

        self.usr_id = str(msg[chat_action]['id'])

        self.photo_url = None
        self.is_self = False

        last_name = msg[chat_action].get('last_name')
        first_name = msg[chat_action].get('first_name')
        self.full_name = ('%s %s' % (first_name, last_name)
                          if first_name and last_name
                          else last_name or first_name)

        self.username = msg[chat_action].get('username')

        user_link = self.get_user_link() if not gpluslink else None

        identifier = 'telesync:' + str(msg['chat']['id'])
        super().__init__(identifier=identifier, user_id=self.usr_id,
                         user_name=self.full_name, user_link=user_link,
                         user_nick=self.username)

        if self.usr_id == '0':
            return
        path = ['telesync', 'user_data', self.usr_id]
        self.bot.memory.ensure_path(path)
        self.bot.memory.get_by_path(path).update(msg[chat_action])

        path += ['last_seen']
        if not (self.bot.memory.exists(path)
                and self.bot.memory.get_by_path(path)):
            # first seen this user or the user has left a chat
            self.bot.memory.set_by_path(path, msg['chat']['id'])

    def get_user_link(self):
        """create a short link with the users username

        Returns:
            string, link to user or None
        """
        if self.username is None:
            return None
        return 'https://t.me/' + self.username

    async def update_user_picture(self, use_cache=True):
        """use the cached user picture or upload a new one

        Args:
            use_cache: boolean, use a cached image and fetch only on cache miss
        """
        base_path = ['telesync', 'user_data', self.usr_id, 'picture']

        if use_cache and self.bot.memory.exists(base_path):
            # pictures are stored in a dict {<image_file_id>: <url>}
            self.photo_url = tuple(
                self.bot.memory.get_by_path(base_path).values())[-1]
            return

        try:
            assert self.usr_id != '0'
            raw = await self.tg_bot.getUserProfilePhotos(self.usr_id)
            photos = raw['photos'][0]
        except (AssertionError, IndexError, KeyError):
            # AssertionError: do not fetch pictures for the fallback user
            # IndexError or KeyError: the user has no profilepicture
            return
        except telepot.exception.TelegramError as err:
            logger.debug('no profile picture available for %s\nReason: %s',
                         self.usr_id, str(err))
            return

        photo = sorted(photos, key=lambda k: k['width'])[- 1]
        path = base_path + [photo['file_id']]

        if self.bot.memory.exists(path):
            self.photo_url = self.bot.memory.get_by_path(path)
            return

        image = await self.tg_bot.get_image(photo)

        image_data, filename = ((None, None) if image is None else
                                image.get_data(limit=500, video_as_gif=True))
        if image_data is None:
            return

        upload_info = await self.bot.sync.get_image_upload_info(image_data,
                                                                filename, 1)
        if upload_info is None:
            return

        # cut the protocol and save '//<rest of url>'
        self.photo_url = upload_info.url.split(':', 1)[-1]

        # reset or init photo data
        self.bot.memory.set_by_path(path[:-1], {})
        self.bot.memory.set_by_path(path, self.photo_url)
        self.bot.memory.save()
