"""enhanced hangups.user.User to provide unified access on other platforms"""
__author__ = 'das7pad@outlook.com'

import logging

import hangups.user

from hangupsbot.base_models import BotMixin

from .utils import get_sync_config_entry

logger = logging.getLogger(__name__)

G_PLUS_URL = 'https://plus.google.com/'


class SyncUser(hangups.user.User, BotMixin):
    """a hangups.user.User-like object with builtin access to profilesyncs

    Args:
        identifier: string, source plugin name
        user: hangups.user.User instance or string as fallback
        user_id: string or hangups.user.UserID, G+ID or platform id
        user_name: string, Fullname
        user_link: string, advaned identifier for cross platform sync
        user_photo: string, url to the user's profile picture
        user_nick: string, custom nickname
        user_is_self: boolean, True if messages should be issued as the bot user
    """
    __slots__ = ('identifier', 'nickname', 'user_link')

    def __init__(self, *, identifier=None, user=None, user_id=None,
                 user_name=None, user_link=None, user_photo=None,
                 user_nick=None, user_is_self=False):
        if isinstance(user, str):
            user_name = user_name or user
        elif isinstance(user, hangups.user.UserID):
            user_id = user.chat_id
        elif user is not None:
            try:
                user_id = user.id_.chat_id
                user_name = user.full_name
                user_photo = user.photo_url
                user_is_self = user.is_self
            except AttributeError:
                logger.exception(
                    '`user` is a hangups.user.User-like object, got %s, dir=%s',
                    type(user), dir(user))

        # get the synced G+ ID, if a platform is registerd for the identifier
        platform = (identifier.rsplit(':', 1)[0] if isinstance(identifier, str)
                    else None)
        if (user_id is not None and platform is not None and
                self.bot.sync.profilesync_provider.get(platform)):
            path = ['profilesync', platform, '2ho']
            user_id = self.bot.memory.get_by_path(path).get(user_id)

        if isinstance(user_id, str) and len(user_id) == 21:
            # try to update the user data with cached data from bot._user_list
            user = self.bot.get_hangups_user(user_id)

            if user.is_default:
                # user is not known/G+ User
                user_name = str(user_name or user.full_name)
                user_photo = user_photo or user.photo_url
            else:
                user_id = user.id_
                user_name = user.full_name
                user_photo = user.photo_url
                # use given user_nick as fallback
                user_nick = self.bot.user_memory_get(user_id.chat_id,
                                                     'nickname') or user_nick

            # allow overrides to True
            user_is_self = bool(user_is_self or user.is_self)

        if not isinstance(user_id, hangups.user.UserID):
            user_id = hangups.user.UserID(chat_id='sync', gaia_id='sync')

        if (isinstance(user_photo, str) and
                user_photo.startswith(('http:', 'https:'))):
            user_photo = user_photo.split(':', 1)[1]

        super().__init__(user_id, user_name, None, user_photo, [], user_is_self)
        self.identifier = identifier

        # ensure a non empty string as nickname or unset it
        self.nickname = user_nick if (isinstance(user_nick, str) and
                                      user_nick) else None

        # ensure a string as custom user_link, or get a G+Link or unset it
        if not isinstance(user_link, str) or not user_link.strip():
            user_link = (G_PLUS_URL + self.id_.chat_id
                         if self.id_.chat_id != 'sync' else None)

        self.user_link = user_link

    def get_displayname(self, conv_id, text_only=False):
        """get either the fullname or firstname plus nickname

        set global/per conv 'sync_nicknames' in config to allow nicknames

        Args:
            conv_id: string, conversation in which the name should be displayed
            text_only: boolean, toggle to do not include the user link

        Returns:
            string
        """
        user_link = self.user_link

        if (self.nickname is not None and
                get_sync_config_entry(self.bot, conv_id, 'sync_nicknames')):
            name_template_key = 'sync_format_name'
        else:
            name_template_key = 'sync_format_name_only'

        name = get_sync_config_entry(
            self.bot, conv_id, name_template_key).format(
                firstname=self.first_name,
                fullname=self.full_name,
                nickname=self.nickname)

        if text_only or user_link is None:
            template = '{name}'
        else:
            template = '<a href="{url}">{name}</a>'

        return template.format(url=user_link, name=name)

    def __str__(self):
        return ('[%s: "%s"|"%s"@%s G+:%s]' %
                (self.__class__.__name__, self.full_name,
                 self.nickname, self.identifier, self.id_.chat_id))
