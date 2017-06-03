"""enhanced hangups conversation that supports a fallback to cached data"""
# pylint: disable=W0212
import logging
import time

import hangups
from hangups import hangouts_pb2

logger = logging.getLogger(__name__)


class HangupsConversation(hangups.conversation.Conversation):
    """Conversation with fallback to permamem

    Args:
        bot: HangupsBot instance
        conv_id: string, Hangouts conversation identifier
    """
    def __init__(self, bot, conv_id):
        self.bot = bot
        self._client = bot._client
        self._user_list = bot._user_list
        # retrieve the conversation record from hangups, if available
        try:
            conversation = bot._conv_list.get(conv_id)._conversation
            super().__init__(self._client, self._user_list, conversation, [])
            return
        except KeyError:
            logger.debug("%s not found in conv list", conv_id)

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

            has_active_hangout=True,
            name=permamem_conv["title"],

            current_participant=current_participant,
            participant_data=participant_data,
            read_state=read_state,

            self_conversation_state=hangouts_pb2.UserConversationState(
                client_generated_id=str(self._client.get_client_generated_id()),
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

        super().__init__(self._client, self._user_list, conversation, [])

    @asyncio.coroutine
    def send_message(self, message, image_id=None, otr_status=None, context=None):

        """ChatMessageSegment: parse message"""

        if message is None:
            # nothing to do if the message is blank
            segments = []
            raw_message = ""
        elif "parser" in context and context["parser"] is False and isinstance(message, str):
            # no parsing requested, escape anything in raw_message that can be construed as valid markdown
            segments = [hangups.ChatMessageSegment(message)]
            raw_message = message.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
        elif isinstance(message, str):
            # preferred method: markdown-formatted message (or less preferable but OK: html)
            segments = simple_parse_to_segments(message)
            raw_message = message
        elif isinstance(message, list):
            # who does this anymore?
            logger.error( "[INVALID]: send messages as html or markdown, "
                          "not as list of ChatMessageSegment, context={}".format(context) )
            segments = message
            raw_message = "".join([ segment_to_html(seg)
                                    for seg in message ])
        else:
            raise TypeError("unknown message type supplied")

        if segments:
            serialised_segments = [seg.serialize() for seg in segments]
        else:
            serialised_segments = None

        if "original_request" not in context["passthru"]:
            context["passthru"]["original_request"] = { "message": raw_message,
                                                        "image_id": image_id,
                                                        "segments": segments }

        """OffTheRecordStatus: determine history"""

        if otr_status is None:
            if "history" not in context:
                context["history"] = True
                try:
                    context["history"] = self.bot.conversations.catalog[self.id_]["history"]

                except KeyError:
                    # rare scenario where a conversation was not refreshed
                    # once the initial message goes through, convmem will be updated
                    logger.warning("could not determine otr for {}".format(self.id_))

            if context["history"]:
                otr_status = hangups_shim.schemas.OffTheRecordStatus.ON_THE_RECORD
            else:
                otr_status = hangups_shim.schemas.OffTheRecordStatus.OFF_THE_RECORD

        """ExistingMedia: attach previously uploaded media for display"""

        media_attachment = None
        if image_id:
            media_attachment = hangups.hangouts_pb2.ExistingMedia(
                photo = hangups.hangouts_pb2.Photo( photo_id = image_id ))

        """EventAnnotation: combine with client-side storage to allow custom messaging context"""

        annotations = []
        if "reprocessor" in context:
            annotations.append( hangups.hangouts_pb2.EventAnnotation(
                type = 1025,
                value = context["reprocessor"]["id"] ))

        # define explicit "passthru" in context to "send" any type of variable
        if "passthru" in context:
            annotations.append( hangups.hangouts_pb2.EventAnnotation(
                type = 1026,
                value = self.bot._handlers.register_passthru(context["passthru"]) ))

        # always implicitly "send" the entire context dictionary
        annotations.append( hangups.hangouts_pb2.EventAnnotation(
            type = 1027,
            value = self.bot._handlers.register_context(context) ))

        """send the message"""

        with (yield from asyncio.Lock()):
            yield from self._client.send_chat_message(
                hangups.hangouts_pb2.SendChatMessageRequest(
                    request_header = self._client.get_request_header(),
                    message_content = hangups.hangouts_pb2.MessageContent( segment=serialised_segments ),
                    existing_media = media_attachment,
                    annotation = annotations,
                    event_request_header = hangups.hangouts_pb2.EventRequestHeader(
                        conversation_id=hangups.hangouts_pb2.ConversationId( id=self.id_ ),
                        client_generated_id=self._client.get_client_generated_id(),
                        expected_otr = otr_status )))
