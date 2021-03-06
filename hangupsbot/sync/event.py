"""enhanced hangups events to provide unified access on other chat platforms"""
__author__ = 'das7pad@outlook.com'
# pylint: disable=too-few-public-methods,too-many-instance-attributes

import asyncio
import logging
from datetime import datetime

import hangups

from hangupsbot.base_models import BotMixin
from .exceptions import MissingArgument
from .image import SyncImage
from .parser import (
    MessageSegment,
    get_formatted,
)
from .user import SyncUser
from .utils import get_sync_config_entry


logger = logging.getLogger(__name__)


class FakeConvEvent:
    """Dummy Event for a Hangups Conversation Event

    Args:
        fake_event (FakeEvent): base instance
        text (mixed): the message as text or in segments in a list
        attachments (list[str]): urls to media
    """

    def __init__(self, fake_event, text, attachments=None):
        self.timestamp = fake_event.timestamp
        self.user_id = fake_event.user.id_
        self.conversation_id = fake_event.conv_id
        self.id_ = fake_event.event_id
        if isinstance(text, str):
            self.segments = MessageSegment.from_str(text)
        elif (isinstance(text, list) and
              all(isinstance(item, hangups.ChatMessageSegment)
                  for item in text)):
            self.segments = text
        else:
            raise TypeError('text is a string or a list of ChatMessageSegments')

        self.attachments = attachments or []

        # membership
        self.type_ = None
        self.participant_ids = []

    @property
    def text(self):
        """get the raw text of the event

        Returns:
            str: raw event text without formatting
        """
        lines = [get_formatted(self.segments, 'text')] + self.attachments
        return '\n'.join(lines)


class FakeEvent(BotMixin):
    """Dummy Event to provide Hangups Event like access to Data around a Message

    Args:
        conv_id (str): Conversation ID for the message
        user (mixed): str or HangupsUser instance
            str, the G+ ID of the sender
            hangups.user.User like object, the sender
        text (mixed): the message as text or in segments in a list
        attachments (list[str]): urls of images for example
    """

    def __init__(self, conv_id=None, user=None, text=None, attachments=None):
        self.timestamp = datetime.now()
        self.event_id = 'fake_event{}'.format(self.timestamp)

        self.conv_id = conv_id
        self.conv = self.bot.get_conversation(conv_id)

        if isinstance(user, str):
            self.user = self.bot.get_hangups_user(user)
        else:
            self.user = user
        self.user_id = self.user.id_
        self.from_bot = bool(self.user.is_self)

        self.conv_event = FakeConvEvent(self, text, attachments)
        self.text = self.conv_event.text


class SyncEvent(FakeEvent):
    """enhanced Event to fake a Hangups Event for a synced Message

    Args:
        identifier (str): platform tag used to identify an Event on receive
        conv_id (str): target Conversation ID for the message
        user (SyncUser): instance of the sender
        text (mixed): str or segment list, raw message from any platform
        targets (list[str]): conversation identifier of relay targets
        previous_targets (set[str]): conv identifier of previous targets
        reply (SyncReply): wrapper with a message to reply
        title (str): Chat Title of the source conversation
        edited (bool): True if the message is an edited message
        image (SyncImage): already wrapped image info
        context (dict): optional information about the message
        notified_users (set[str]): object to track users that were notified for
            the message content
    """

    def __init__(self, *, identifier=None, conv_id, user, text=None,
                 targets=None, reply=None, title=None, edited=None, image=None,
                 context=None, notified_users=None, previous_targets=None):

        # validate user or create one
        user = (user if isinstance(user, SyncUser)
                else SyncUser(identifier=identifier, user=user))

        self.identifier = identifier
        self.targets = targets if isinstance(targets, list) else []
        self.image = image if isinstance(image, SyncImage) else None
        self.reply = reply if isinstance(reply, SyncReply) else None
        self.context = context if isinstance(context, dict) else {}

        # keep the reference of notified_users, to track them in all other convs
        self.notified_users = (
            {user.id_.chat_id} if notified_users is None else notified_users)
        self.previous_targets = (
            {identifier} if previous_targets is None else previous_targets)
        self.user_list = None
        self.syncroom_no_repeat = False

        self.edited = edited or False

        if self.bot.memory.exists(['chattitle', identifier]):
            self._title = self.bot.memory.get_by_path(['chattitle', identifier])
            self.display_title = title or self._title
        else:
            self.display_title = self._title = title or ''

        text = text or []

        # build the base FakeEvent
        super().__init__(conv_id, user, text=text)

    ############################################################################
    # PUBLIC METHODS
    ############################################################################

    def title(self, conv_id=None):
        """get a shot custom or long live title of the source conversation

        Args:
            conv_id (str): conv identifier of the target conversation

        Returns:
            str: long or short version of the title
        """
        if conv_id is None:
            conv_id = self.conv_id
        return (self.display_title if get_sync_config_entry(self.bot, conv_id,
                                                            'sync_title_long')
                else self._title)

    async def get_image_url(self, conv_id=None):
        """get a public url to the image that is connected to this event

        Args:
            conv_id (str): a custom identifier to pick the config entries from

        Returns:
            mixed: a url or error message (str) or None if no image is available
        """
        upload_info = await self._base_image_upload(conv_id, video_as_gif=True)

        if isinstance(upload_info, hangups.client.UploadedImage):
            return upload_info.url

        return upload_info

    async def get_image_id(self, conv_id=None):
        """get an upload id of the resized image connected to the event

        Args:
            conv_id (str): a custom identifier to pick the config entries from

        Returns:
            mixed: the upload id (int) or None if no image is available
        """
        upload_info = await self._base_image_upload(conv_id)

        if not isinstance(upload_info, hangups.client.UploadedImage):
            return None

        self.conv_event.attachments = [upload_info.url]
        # update the text with the new url
        self.text = self.conv_event.text
        return upload_info.image_id

    async def get_image(self, conv_id=None, video_as_gif=False):
        """get the image connected to the event with resized image data

        Args:
            conv_id (str): a custom identifier to pick the config entries from
            video_as_gif (bool): toggle to get videos as gif

        Returns:
            tuple[SyncImage, io.ByesIO, str]: the complete image data, the
                resized image data and the filename
            If no image is available return None, None, None
        """
        image, limit = self._get_image_raw(conv_id=conv_id)
        if image is None:
            return None, None, None

        image_data, filename = await asyncio.get_event_loop().run_in_executor(
            None, image.get_data, limit, video_as_gif)

        if image_data is not None:
            image_data.seek(0)
        return image, image_data, filename

    async def process(self):
        """fetch the user list, process the image"""
        self.user_list = await self.bot.sync.get_users_in_conversation(
            self.conv_id, profilesync_only=True)

        image = self._get_image_raw()[0]
        if image is None:
            return

        await image.process()

    def get_segments(self, text=None):
        """get hangups.ChatMessageSegments from .text or text

        Args:
            text (mixed): string or list of hangups.ChatMessageSegments

        Returns:
            list[hangups.ChatMessageSegment]: parsed formatting segments
        """
        if isinstance(text, str):
            return MessageSegment.from_str(text)

        if isinstance(text, list):
            return text

        return self.conv_event.segments

    def get_formatted_text(self, *, style='hangouts', template=None, text=None,
                           title=None, name=None, add_photo_tag=None,
                           names_text_only=False, conv_id=None):
        """create a formatted text for the event with applied style

        Args:
            style (mixed): string or dict, target style key in
                `sync.parser.STYLE_MAPPING` or own dict
            template (str): a custom format string, available keys:
                edited, name, reply, separator, text, title
            text (str): override the original text of the message
            title (str): override the original title of the chat
            name (str): override the original sender of the message
            add_photo_tag (bool): True/False forces the prefix with image tag
                defaults to the existance of an image
            names_text_only (bool): on True do not include a url into the name
            conv_id (str): identifier for a conversation to pick the config
                entries from

        Returns:
            str: final event text
        """
        bot = self.bot
        if conv_id is None:
            conv_id = self.conv_id
        if not isinstance(name, str):
            name = self.user.get_displayname(conv_id, text_only=names_text_only)

        segments = self.get_segments(text=text)

        image_tag = ''
        if (add_photo_tag is True or
                (self.image is not None and add_photo_tag is not False)):
            # use the photo tag as fallback for missing image
            key = 'sync_tag_{}'.format(self.image.type_
                                       if self.image is not None else 'photo')

            image_tag = get_sync_config_entry(self.bot, conv_id, key)

            # ensure one space to the left of the tag
            image_tag = image_tag.rstrip() + ' '

        if isinstance(template, str):
            # override
            pass
        elif self.user.is_self:
            template = get_sync_config_entry(bot, conv_id, 'format_message_bot')
        else:
            template = get_sync_config_entry(bot, conv_id, 'format_message')

        title = title or ''
        if get_sync_config_entry(bot, conv_id, 'sync_title'):
            title = title or self.title(conv_id) or ''
            if isinstance(title, str) and title:
                title = get_sync_config_entry(
                    bot, conv_id, 'format_title').format(title=title)

        edited_tag = (get_sync_config_entry(bot, conv_id, 'sync_tag_edited')
                      if self.edited else '')

        reply = self.get_reply_text(conv_id) if '{reply}' in template else None

        text = template.format(reply=reply,
                               edited=edited_tag,
                               name=name,
                               title=title,
                               image_tag=image_tag,
                               text=get_formatted(segments, 'internal'),
                               separator=bot.config['sync_separator'])
        return get_formatted(text, style, internal_source=True)

    def get_reply_text(self, conv_id):
        """forward call to reply

        Args:
            conv_id (str): target conversation

        Returns:
            str: formatted reply text or empty string if no reply is available
        """
        # skip if no reply is available or should be synced to the given conv
        if self.reply is None:
            return ''

        return self.reply.get_formatted_text(conv_id)

    ############################################################################
    # PRIVATE METHODS
    ############################################################################

    def _get_image_raw(self, conv_id=None):
        """get the main image or the image of the reply

        assume that only the message or the reply can contain an image, check
        the main image first and ignore the reply image then

        Args:
            conv_id (str): a custom identifier to pick the config entries from

        Returns:
            tuple[SyncImage, int]: the image or None if no image is available
                and the new image size limit
        """
        conv_id = conv_id or self.conv_id

        if self.image is None:
            if self.reply is None or self.reply.image is None:
                return None, 0
            spam_offset = get_sync_config_entry(self.bot, self.conv_id,
                                                'reply_spam_offset')
            if self.reply.offset < spam_offset:
                return None, 0
            image = self.reply.image
            source = 'reply_'
        else:
            image = self.image
            source = ''

        key = 'sync_' + source + image.type_
        if not get_sync_config_entry(self.bot, conv_id, key):
            return None, 0

        if self.edited:
            key = 'sync_{}_on_edit'.format(image.type_)
            if not get_sync_config_entry(self.bot, conv_id, key):
                return None, 0

        key = 'sync_{}size_{}'.format(source, image.type_)
        return image, get_sync_config_entry(self.bot, conv_id, key)

    async def _base_image_upload(self, conv_id, video_as_gif=False):
        """perform the base image upload

        Args:
            conv_id (str): a custom identifier to pick the config entries from
            video_as_gif (bool): set to True to get videos as gif

        Returns:
            None: the upload failed or the event has no image
            string: no image data is available, a custom error message
            hangups.client.UploadedImage instance: on a successful image upload
        """
        image, image_data, filename = await self.get_image(
            conv_id=conv_id, video_as_gif=video_as_gif)

        if image_data is None:
            return filename

        upload_info = await self.bot.sync.get_image_upload_info(
            image_data, filename, image.cache)
        image_data.close()

        if upload_info is None:
            return None

        return upload_info

    def __str__(self):
        return ("%s: %s@%s for %s [%s]: %s" %
                (self.__class__.__name__, self.user, self.identifier,
                 self.conv_id, self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                 self.text))


class SyncEventMembership(SyncEvent):
    """Membership Event similar to the hangups.MembershipChangeEvent

    Args:
        identifier (str): platform tag used to identify an Event on receive
        conv_id (str): target Conversation ID for the message
        title (str): Chat Title of the source conversation
        user (hangupsbot.sync.user.SyncUser): instance of the sender
        text (mixed): str or segment list, raw message from any platform
        targets (list[str]): conversation identifier of relay targets
        previous_targets (set[str]): conv identifier
        type_ (int): 1: join, 2: leave - same as the hangups values
        participant_user (mixed): the changed members
            None: self add or leave,
            SyncUser: one user added or kicked,
            list[SyncUser]: multiple users added or kicked,
            or list[str]: representing each a username or chat_id
        notified_users (set[str]): object to track users that were notified for
            the message content
    """

    def __init__(self, *, identifier=None, conv_id=None, title=None, user=None,
                 text=None, targets=None, type_=None, participant_user=None,
                 notified_users=None, previous_targets=None):

        if type_ not in (1, 2):
            raise MissingArgument(
                'membership change types: 1 (join) or 2 (leave), got %s'
                % type_)

        # build the base SyncEvent
        super().__init__(identifier=identifier, conv_id=conv_id, user=user,
                         text=text, targets=targets, title=title,
                         notified_users=notified_users,
                         previous_targets=previous_targets)

        if not isinstance(participant_user, list):
            if participant_user is None:
                participant_user = []
            else:
                participant_user = [participant_user]

        self.participant_user = []
        for p_user in participant_user:
            if not isinstance(p_user, SyncUser):
                p_user = SyncUser(identifier=identifier, user=p_user)
            self.participant_user.append(p_user)

        self.conv_event.type_ = self.type_ = type_

        # extract valid G+ Ids
        self.conv_event.participant_ids = [p_user.id_
                                           for p_user in self.participant_user
                                           if p_user.id_.chat_id != 'sync']

    # pylint:disable=arguments-differ
    def get_formatted_text(self, *, style='hangouts', text=None, title=None,
                           name=None, template=None, names_text_only=False,
                           conv_id=None):
        """create a formatted text for the event with applied style

        Args:
            style (mixed): string or dict, target style key in
                `sync.parser.STYLE_MAPPING` or own dict
            text (str): override the original text of the message
            title (str): override the original title of the chat
            name (str): override the original sender of the message
            template (str): a custom format string, available keys:
                edited, name, reply, separator, text, title
            names_text_only (bool): on True do not include a url into the name
            conv_id (str): identifier for a conversation to pick the config
                entries from

        Returns:
            mixed: final text (str) or None if no text should be send
        """
        bot = self.bot
        if conv_id is None:
            conv_id = self.conv_id

        config_entry = ('sync_membership_join' if self.type_ == 1 else
                        'sync_membership_leave')

        if not get_sync_config_entry(bot, conv_id, config_entry):
            return None

        if not isinstance(name, str):
            name = self.user.get_displayname(conv_id,
                                             text_only=names_text_only)

        text = self.get_segments(text=text)

        if not isinstance(template, str):
            if self.participant_user:
                suffix = 'add' if self.type_ == 1 else 'kick'
            else:
                suffix = 'join' if self.type_ == 1 else 'leave'

            template = get_sync_config_entry(bot, conv_id,
                                             'format_membership_' + suffix)

            if get_sync_config_entry(bot, conv_id, 'sync_title'):
                title = title or self.title(conv_id) or ''
                if not isinstance(title, str):
                    title = bot.conversations.get_name(conv_id, '')
                if title:
                    title_template = get_sync_config_entry(
                        bot, conv_id, 'format_title_membership_' + suffix)
                    title = title_template.format(title=title)
            else:
                title = ''

        participants = ', '.join(
            (user.get_displayname(conv_id, text_only=names_text_only)
             for user in self.participant_user))

        text = template.format(name=name, participants=participants,
                               text=get_formatted(text, 'internal'),
                               title=title)
        return get_formatted(text, style, internal_source=True)


class SyncReply(BotMixin):
    """wrapper for reply messages

    Args:
        identifier (str): platform tag used to identify an Event on receive
        user (mixed): str or SyncUser instance, sender of the original message
        text (str): original message
        offset (int): message count between the original message and the reply
        image (hangupsbot.sync.image.SyncImage): opt, the image one replies to
    """

    def __init__(self, *, identifier=None, user=None, text=None, offset=None,
                 image=None):

        # validate user or create one
        if not isinstance(user, SyncUser):
            user = SyncUser(identifier=identifier, user=user)

        self.user = user
        self.text = text

        # ensure an offset of type integer, an offset of <1 is not possible
        self.offset = offset if isinstance(offset, int) and offset > 0 else 99

        # validate a given image or unset it
        self.image = image if isinstance(image, SyncImage) else None

    def get_formatted_text(self, conv_id):
        """check the sender user and create the formatted reply message

        Args:
            conv_id (str): target conversation

        Returns:
            str: the formatted message
        """
        bot = self.bot
        if not get_sync_config_entry(bot, conv_id, 'sync_reply'):
            return ''

        r_user = self.user
        spam_offset = get_sync_config_entry(self.bot, conv_id,
                                            'reply_spam_offset')

        r_text = self.text if self.offset > spam_offset else ''

        # append the cases to the key
        template_key = 'format_reply'
        if r_user.is_self:
            template_key += '_bot'

        r_text = r_text or ''

        if self.image is not None:
            # add the photo tag
            type_ = self.image.type_
            image_tag = self.bot.config.get_option('sync_tag_{}'.format(type_))
            r_text = r_text.replace(image_tag.strip(), '').strip()
            image_tag = image_tag.rstrip() + ' '

        else:
            image_tag = ''

        if r_text:
            limit = get_sync_config_entry(bot, conv_id, 'reply_limit')
            r_text = r_text if len(r_text) < limit else r_text[0:limit] + '...'
        else:
            template_key += '_empty'

        return get_sync_config_entry(bot, conv_id, template_key).format(
            name=r_user.get_displayname(conv_id, text_only=True), text=r_text,
            image_tag=image_tag)
