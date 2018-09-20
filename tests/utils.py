"""utils for testing"""

# TODO(das7pad): documentation
__all__ = (
    'Message',
    'simple_conv_list',
    'simple_user_list',
    'build_user_conversation_list_base',
    'run_cmd',
)
import time
from collections import namedtuple

import hangups
import hangups.parsers
from hangups import hangouts_pb2
from hangups.user import (
    User,
    UserID,
)

from hangupsbot.commands import command
from tests.constants import (
    CHAT_ID_1,
    CHAT_ID_2,
    CHAT_ID_BOT,
    CONV_ID_1,
    CONV_ID_2,
    CONV_ID_3,
    CONV_NAME_1,
    CONV_NAME_2,
    CONV_NAME_3,
    DEFAULT_TIMESTAMP,
    USER_EMAIL_BOT,
    USER_NAME_1,
    USER_NAME_2,
    USER_NAME_BOT,
    USER_PHOTO_1,
    USER_PHOTO_2,
    USER_PHOTO_BOT,
)


Message = namedtuple('Message', ['conv_id', 'text', 'context', 'image_id'])
ConvData = namedtuple('ConvData', ('id_', 'name', 'users'))


class _User(User):
    def to_entity(self):
        chat_id = self.id_.chat_id
        return hangouts_pb2.Entity(
            id=hangouts_pb2.ParticipantId(
                chat_id=chat_id, gaia_id=chat_id),
            properties=hangouts_pb2.EntityProperties(
                display_name=self.full_name,
                first_name=self.first_name,
                photo_url=self.photo_url))


class SimpleConvList(dict):
    def __init__(self, *raw_data):
        super().__init__({conv_id: ConvData(conv_id, name, users)
                          for conv_id, name, users in raw_data})

    def get_conv_data(self, conv_id):
        return self[conv_id]

    def get_name(self, conv_id):
        return self[conv_id].name

    def get_users(self, conv_id):
        return self[conv_id].users


class SimpleUserList(dict):
    def __init__(self, *raw_data):
        super().__init__(
            {chat_id: _User(UserID(chat_id, chat_id), name, None, photo,
                            [email] if email else None, chat_id == CHAT_ID_BOT)
             for chat_id, name, photo, email in raw_data})

    def get_user(self, chat_id):
        return self[chat_id]

    def get_name(self, chat_id):
        return self[chat_id].full_name

    def get_photo(self, chat_id):
        return self[chat_id].photo_url


simple_conv_list = SimpleConvList(
    (CONV_ID_1, CONV_NAME_1, (CHAT_ID_1, CHAT_ID_2, CHAT_ID_BOT)),
    (CONV_ID_2, CONV_NAME_2, (CHAT_ID_1, CHAT_ID_BOT)),

    # this conversation is not part of the event fixtures
    (CONV_ID_3, CONV_NAME_3, (CHAT_ID_2, CHAT_ID_BOT)),
)

simple_user_list = SimpleUserList(
    (CHAT_ID_BOT, USER_NAME_BOT, USER_PHOTO_BOT, USER_EMAIL_BOT),
    (CHAT_ID_1, USER_NAME_1, USER_PHOTO_1, None),
    (CHAT_ID_2, USER_NAME_2, USER_PHOTO_2, None),
)


def build_user_conversation_list_base():
    """get the protobuf-based params for `hangups.UserList`, `.ConversationList`

    Returns:
        tuple[dict, dict]: kwargs for the user list and kwargs for the conv list
    """
    get_client_generated_id = hangups.Client.get_client_generated_id

    self_entity = simple_user_list.get_user(CHAT_ID_BOT).to_entity()
    users = [user.to_entity() for user in simple_user_list.values()]

    now = int(time.time() * 1000000)
    conv_states = []
    for conv_id, conv in simple_conv_list.items():
        current_participants = []
        participant_data = []
        read_state = []

        for chat_id in conv.users:
            user = simple_user_list.get_user(chat_id)
            part_id = hangouts_pb2.ParticipantId(
                chat_id=chat_id, gaia_id=chat_id)

            current_participants.append(part_id)

            participant_data.append(hangouts_pb2.ConversationParticipantData(
                fallback_name=user.full_name,
                id=part_id))

            read_state.append(hangouts_pb2.UserReadState(
                latest_read_timestamp=now, participant_id=part_id))

        conversation = hangouts_pb2.Conversation(
            conversation_id=hangouts_pb2.ConversationId(id=conv_id),
            type=(hangouts_pb2.CONVERSATION_TYPE_ONE_TO_ONE
                  if len(conv.users) == 2 else
                  hangouts_pb2.CONVERSATION_TYPE_GROUP),
            has_active_hangout=False,
            name=conv.name,
            current_participant=current_participants,
            participant_data=participant_data,
            read_state=read_state,

            self_conversation_state=hangouts_pb2.UserConversationState(
                client_generated_id=str(get_client_generated_id()),
                self_read_state=hangouts_pb2.UserReadState(
                    latest_read_timestamp=now,
                    participant_id=hangouts_pb2.ParticipantId(
                        chat_id=CHAT_ID_BOT, gaia_id=CHAT_ID_BOT)),
                status=hangouts_pb2.CONVERSATION_STATUS_ACTIVE,
                notification_level=hangouts_pb2.NOTIFICATION_LEVEL_RING,
                view=[hangouts_pb2.CONVERSATION_VIEW_INBOX],
                delivery_medium_option=[hangouts_pb2.DeliveryMediumOption(
                    delivery_medium=hangouts_pb2.DeliveryMedium(
                        medium_type=hangouts_pb2.DELIVERY_MEDIUM_BABEL))]),

            conversation_history_supported=True,
            otr_status=hangouts_pb2.OFF_THE_RECORD_STATUS_ON_THE_RECORD,
            otr_toggle=hangouts_pb2.OFF_THE_RECORD_TOGGLE_ENABLED,

            network_type=[hangouts_pb2.NETWORK_TYPE_BABEL],
            force_history_state=hangouts_pb2.FORCE_HISTORY_NO,
            group_link_sharing_status=hangouts_pb2.GROUP_LINK_SHARING_STATUS_OFF
        )
        conv_states.append(
            hangouts_pb2.ConversationState(conversation=conversation,
                                           event=()))

    return (dict(self_entity=self_entity,
                 entities=users,
                 conv_parts=()),
            dict(conv_states=conv_states,
                 sync_timestamp=hangups.parsers.from_timestamp(
                     DEFAULT_TIMESTAMP)))


async def run_cmd(bot, event):
    kwargs = dict(__return_result__=True, raise_exceptions=True)
    return await command.run(bot, event, *event.text.split()[1:], **kwargs)
