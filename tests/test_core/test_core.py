"""test `hangupsbot.core.HangupsBot`"""
__author__ = 'das7pad@outlook.com'

import asyncio
from unittest import mock

import hangups
import pytest
from aioresponses import aioresponses

import hangupsbot.core
import hangupsbot.hangups_conversation

from tests.constants import DEFAULT_BOT_KWARGS
from tests.utils import build_user_conversation_list_base

NOOP = b'1\n[[1,["noop"]\n]\n]\n'
GSESSIONID = b'52\n[[0,["c","MYSID","",8]\n]\n,[1,[{"gsid":"MYGSID"}]]\n]\n'
LONG_POLLING_URL = hangups.channel.CHANNEL_URL_PREFIX.format('channel/bind')
USER_LIST_KWARGS, CONV_LIST_KWARGS = build_user_conversation_list_base()

async def build_user_conversation_list(client, **kwargs):
    user_list = hangups.UserList(client, **USER_LIST_KWARGS)
    conv_list = hangupsbot.hangups_conversation.HangupsConversationList(
        client, user_list=user_list, **CONV_LIST_KWARGS)
    return user_list, conv_list

def test_hangupsbot_run():
    class _TestHangupsBot(hangupsbot.core.HangupsBot):
        async def _on_connect(self):
            await super()._on_connect()
            self.stop()
            await asyncio.sleep(5)  # delay further requests

    with mock.patch('hangups.get_auth_stdin') as get_auth_stdin:
        get_auth_stdin.return_value = {'SAPISID': 'IS_REQUIRED'}

        with aioresponses() as aiohttp_mock:
            # hangups.channel.Channel._fetch_channel_sid
            aiohttp_mock.post(LONG_POLLING_URL, body=GSESSIONID)

            # hangups.channel.Channel._longpoll_request
            aiohttp_mock.get(LONG_POLLING_URL, body=NOOP)
            aiohttp_mock.get(LONG_POLLING_URL, body=NOOP)

            with mock.patch('hangups.build_user_conversation_list',
                            new=build_user_conversation_list):

                bot_ = _TestHangupsBot(**DEFAULT_BOT_KWARGS)
                bot_.config['plugins'] = ()
                with pytest.raises(SystemExit):
                    bot_.run()
