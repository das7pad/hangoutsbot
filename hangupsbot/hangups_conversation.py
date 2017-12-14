"""enhanced hangups conversation that supports a fallback to cached data"""
import logging
import time

import hangups
from hangups import hangouts_pb2

from hangupsbot.base_models import BotMixin
from hangupsbot.sync.parser import MessageSegmentHangups

logger = logging.getLogger(__name__)


class HangupsConversation(hangups.conversation.Conversation, BotMixin):
    """Conversation with fallback to permamem

    Args:
        see `hangups.conversation.Conversation`
    """
    @classmethod
    def from_permamem(cls, bot, conv_id):
        # pylint:disable=protected-access
        client = bot._client
        user_list = bot._user_list
        # pylint:enable=protected-access

        # retrieve the conversation record from permamem
        try:
            permamem_conv = bot.conversations[conv_id]
        except KeyError:
            logger.warning("%s not found in permamem", conv_id)
            permamem_conv = {
                "title": "I GOT KICKED",
                "type": "GROUP",
                "history": False,
                "status": "DEFAULT",
                "link_sharing": False,
                "participants": [],
            }

        # set some basic variables
        bot_chat_id = bot.user_self()["chat_id"]

        otr_status = (hangouts_pb2.OFF_THE_RECORD_STATUS_ON_THE_RECORD
                      if permamem_conv["history"] else
                      hangouts_pb2.OFF_THE_RECORD_STATUS_OFF_THE_RECORD)

        status = (hangouts_pb2.CONVERSATION_STATUS_INVITED
                  if permamem_conv["status"] == "INVITED" else
                  hangouts_pb2.CONVERSATION_STATUS_ACTIVE)

        current_participant = []
        participant_data = []
        read_state = []
        now = int(time.time() * 1000000)

        for chat_id in set(permamem_conv["participants"] + [bot_chat_id]):
            part_id = hangouts_pb2.ParticipantId(chat_id=chat_id,
                                                 gaia_id=chat_id)

            current_participant.append(part_id)

            participant_data.append(hangouts_pb2.ConversationParticipantData(
                fallback_name=bot.get_hangups_user(chat_id).full_name,
                id=part_id))

            read_state.append(hangouts_pb2.UserReadState(
                latest_read_timestamp=now, participant_id=part_id))

        conversation = hangouts_pb2.Conversation(
            conversation_id=hangouts_pb2.ConversationId(id=conv_id),

            type=(hangouts_pb2.CONVERSATION_TYPE_GROUP
                  if permamem_conv["type"] == "GROUP" else
                  hangouts_pb2.CONVERSATION_TYPE_ONE_TO_ONE),

            has_active_hangout=False,
            name=permamem_conv["title"],

            current_participant=current_participant,
            participant_data=participant_data,
            read_state=read_state,

            self_conversation_state=hangouts_pb2.UserConversationState(
                client_generated_id=str(client.get_client_generated_id()),
                self_read_state=hangouts_pb2.UserReadState(
                    latest_read_timestamp=now,
                    participant_id=hangouts_pb2.ParticipantId(
                        chat_id=bot_chat_id, gaia_id=bot_chat_id)),
                status=status,
                notification_level=hangouts_pb2.NOTIFICATION_LEVEL_RING,
                view=[hangouts_pb2.CONVERSATION_VIEW_INBOX],
                delivery_medium_option=[hangouts_pb2.DeliveryMediumOption(
                    delivery_medium=hangouts_pb2.DeliveryMedium(
                        medium_type=hangouts_pb2.DELIVERY_MEDIUM_BABEL))]),

            conversation_history_supported=True,
            otr_status=otr_status,
            otr_toggle=(hangouts_pb2.OFF_THE_RECORD_TOGGLE_ENABLED
                        if status == hangouts_pb2.CONVERSATION_STATUS_ACTIVE
                        else hangouts_pb2.OFF_THE_RECORD_TOGGLE_DISABLED),

            network_type=[hangouts_pb2.NETWORK_TYPE_BABEL],
            force_history_state=hangouts_pb2.FORCE_HISTORY_NO,
            group_link_sharing_status=(
                hangouts_pb2.GROUP_LINK_SHARING_STATUS_ON
                if permamem_conv['link_sharing'] else
                hangouts_pb2.GROUP_LINK_SHARING_STATUS_OFF))

        return cls(client, user_list, conversation, [])

    @property
    def name(self):
        """get the custom title or generate one from participant names

        Returns:
            string
        """
        return self.bot.conversations.get_name(self)

    def add_event(self, event_):
        """process an event for the conversation

        drops the memory leak in hangups from storing all events permanent

        Args:
            event_ (hangups.hangouts_pb2.Event): message, membership, etc.

        Returns:
            hangups.ConversationEvent: the derived conv_event
        """
        return self._wrap_event(event_)

    async def send_message(self, message, image_id=None, context=None):
        """send a message to Hangouts

        Args:
            message: string, list of hangups.ChatMessageSegment or None,
                the text part of the message which can be empty
            image_id: string or integer, the upload id of an image,
                acquire one from ._client.upload_image(...)
            context: dict, additional information about the message,
                including 'reprocessor' or chatbridge entries

        Raises:
            TypeError: invalid message text provided
            ValueError: no image and also no text provided
        """
        # pylint:disable=arguments-differ
        context = context or {"__ignore__": True}        # replace empty context

        # parse message
        if not message or isinstance(message, str) and not message.strip():
            # nothing to do if the message is blank
            segments = []

        elif ("parser" in context and context["parser"] is False and
              isinstance(message, str)):
            # pre-formatted string
            segments = [hangups.ChatMessageSegment(message)]

        elif isinstance(message, str):
            # markdown- or html-formatted message
            segments = MessageSegmentHangups.from_str(message)

        elif (isinstance(message, list)
              and all(isinstance(item, hangups.ChatMessageSegment)
                      for item in message)):
            # a list of hangups.ChatMessageSegment
            segments = message

        else:
            raise TypeError("unknown message type supplied")

        serialised_segments = [seg.serialize() for seg in segments] or None

        if image_id is None and serialised_segments is None:
            # no message content
            raise ValueError("no image or text provided")

        # EventAnnotation:
        # combine with client-side storage to allow custom messaging context
        annotations = []
        if "reprocessor" in context:
            annotations.append(hangouts_pb2.EventAnnotation(
                type=1025,
                value=context["reprocessor"]["id"]))
            context.pop("reprocessor")

        # save entire context unless it was explicit suppressed
        if context and "__ignore__" not in context:
            # pylint: disable=protected-access
            annotations.append(hangouts_pb2.EventAnnotation(
                type=1027,
                value=self.bot._handlers.register_context(context)))

        kwargs = dict(
            request_header=self._client.get_request_header(),
            message_content=hangouts_pb2.MessageContent(
                segment=serialised_segments),
            annotation=annotations,
            event_request_header=self._get_event_request_header(),
        )
        if image_id is not None:
            kwargs['existing_media'] = hangouts_pb2.ExistingMedia(
                photo=hangouts_pb2.Photo(photo_id=image_id))

        request = hangouts_pb2.SendChatMessageRequest(**kwargs)

        try:
            # send the message
            await self._client.send_chat_message(request)
        except hangups.NetworkError as err:
            logger.error('%s on sending to %s:\n%s\nimage=%s\n',
                         repr(err), self.id_, serialised_segments, image_id)


class HangupsConversationList(hangups.conversation.ConversationList, BotMixin):
    conv_cls = HangupsConversation

    def get(self, conv_id):
        """Get a conversation gracefully by its identifier.

        Args:
            conv_id (str): conversation identifier of conversation to return.

        Returns:
            HangupsConversation: a cached conv or permamem fallback
        """
        if conv_id in self._conv_dict:
            return self._conv_dict[conv_id]

        conv = self.conv_cls.from_permamem(self.bot, conv_id)
        self._conv_dict[conv_id] = conv
        return conv

    def __iter__(self):
        return iter(self._conv_dict)
