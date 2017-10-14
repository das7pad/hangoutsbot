"""utils for testing"""

# TODO(das7pad): documentation
__all__ = (
    'simple_conv_list',
    'simple_user_list',
)
from collections import namedtuple

from hangups import hangouts_pb2
from hangups.user import User, UserID

from tests.constants import (
    CONV_ID_1,
    CONV_ID_2,
    CONV_ID_3,
    CONV_NAME_1,
    CONV_NAME_2,
    CONV_NAME_3,
    CHAT_ID_BOT,
    CHAT_ID_1,
    CHAT_ID_2,
    USER_NAME_BOT,
    USER_NAME_1,
    USER_NAME_2,
    USER_EMAIL_BOT,
    USER_PHOTO_BOT,
    USER_PHOTO_1,
    USER_PHOTO_2,
)

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
