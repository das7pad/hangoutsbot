"""constants for the tests"""

__all__ = (
    'CHAT_ID_1',
    'CHAT_ID_2',
    'CHAT_ID_ADMIN',
    'CHAT_ID_BOT',
    'CONFIG_DATA',
    'CONFIG_PATH',
    'CONV_ID_1',
    'CONV_ID_2',
    'CONV_ID_3',
    'CONV_NAME_1',
    'CONV_NAME_2',
    'CONV_NAME_3',
    'USER_EMAIL_BOT',
    'USER_NAME_1',
    'USER_NAME_2',
    'USER_NAME_BOT',
    'USER_PHOTO_1',
    'USER_PHOTO_2',
    'USER_PHOTO_BOT',
)

import json
import os

_BASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          '.cache')
CONFIG_PATH = os.path.join(_BASE_PATH, 'config.json')
del _BASE_PATH
CONV_ID_1 = 'CONV_ID_1'
CONV_ID_2 = 'CONV_ID_2'
CONV_ID_3 = 'CONV_ID_3'
CONV_NAME_1 = 'CONV_NAME_1'
CONV_NAME_2 = 'CONV_NAME_2'
CONV_NAME_3 = 'CONV_NAME_3'

CHAT_ID_BOT = '111111111111111111111'
CHAT_ID_ADMIN = CHAT_ID_1 = '123456789101112131415'
CHAT_ID_2 = '514131211101987654321'
USER_NAME_BOT = 'FirstnameBOT LastnameBOT'
USER_NAME_1 = 'Firstname1 Lastname1'
USER_NAME_2 = 'Firstname2 Lastname2'
USER_EMAIL_BOT = 'bot@example.com'
USER_PHOTO_BOT = '//example.com/image.jpg'
USER_PHOTO_1 = None
USER_PHOTO_2 = '//example.com/picture.jpg'

CONFIG_DATA = {
    'admins': [
        CHAT_ID_ADMIN,
    ],
    'conversations': {
        CONV_ID_1: {
            'PER_CONV': True
        }
    },
    'one': {
        'two': {
            'three': None
        }
    },
    'GLOBAL': True,
    'PER_CONV': False,
}
CONFIG_DATA_DUMPED = json.dumps(CONFIG_DATA, sort_keys=True, indent=2)
