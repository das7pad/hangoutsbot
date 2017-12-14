"""Hangups Events to Hangupsbot event mapping

the following events provide the properties that are in general needed to
identify a user of a message, the message content and the conversation
"""
#pylint: disable=too-few-public-methods, too-many-instance-attributes

import logging

from hangups import TYPING_TYPE_STARTED, TYPING_TYPE_PAUSED, ChatMessageEvent

from hangupsbot.base_models import BotMixin


logger = logging.getLogger(__name__)


class GenericEvent(BotMixin):
    """base event that sets logging

    Args:
        conv_event: an event instance from hangups.conversation_event or
         one of hangups.parsers.{TypingStatusMessage, WatermarkNotification}
        conv_id: string, conversation identifier
    """
    def __init__(self, conv_event, conv_id):
        self.conv_event = conv_event
        self.conv_id = conv_id
        self.conv = self.bot.get_conversation(self.conv_id)
        self.event_id = None
        self.user_id = conv_event.user_id
        self.user = self.bot.get_hangups_user(self.user_id)
        self.timestamp = None
        self.text = ''
        self.from_bot = self.user.is_self

    def __str__(self):
        return ("%s: %s@%s [%s]: %s" %
                (self.__class__.__name__, self.user_id.chat_id, self.conv_id,
                 self.timestamp.astimezone().strftime('%Y-%m-%d %H:%M:%S'),
                 self.text))


class TypingEvent(GenericEvent):
    """user starts/pauses/stops typing

    Args:
        state_update_event: hangups.parsers.TypingStatusMessage instance
    """
    def __init__(self, state_update_event):
        super().__init__(state_update_event, state_update_event.conv_id)
        self.timestamp = state_update_event.timestamp
        status = state_update_event.status
        self.text = ('typing started' if status == TYPING_TYPE_STARTED
                     else 'typing paused' if status == TYPING_TYPE_PAUSED
                     else 'typing stopped')


class WatermarkEvent(GenericEvent):
    """user reads up to a certain point in the conversation

    Args:
        state_update_event: hangups.parsers.WatermarkNotification instance
    """
    def __init__(self, state_update_event):
        super().__init__(state_update_event, state_update_event.conv_id)
        self.timestamp = state_update_event.read_timestamp
        self.text = "watermark"


class ConversationEvent(GenericEvent):
    """user joins, leaves, renames or messages a conversation

    Args:
        conv_event: an event instance from hangups.conversation_event
    """
    def __init__(self, conv_event):
        super().__init__(conv_event, conv_event.conversation_id)

        self.event_id = conv_event.id_
        self.timestamp = conv_event.timestamp
        self.text = (conv_event.text.strip()
                     if isinstance(conv_event, ChatMessageEvent)
                     else '')
        self.log()

    def log(self):
        """log meta of the event"""
        logger.info('eid/dt: %s/%s', self.event_id,
                    self.timestamp.astimezone().strftime('%Y-%m-%d %H:%M:%S'))
        logger.info('cid/cn: %s/%s',
                    self.conv_id, self.bot.conversations.get_name(self.conv))
        logger.info('  c/un: %s/%s',
                    self.user_id.chat_id, self.user.full_name)
        logger.info('len/tx: %s/%s', len(self.text), self.text)
