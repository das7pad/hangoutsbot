"""test `hangupsbot.core.HangupsBot`"""
__author__ = 'das7pad@outlook.com'

import asyncio
import os
from unittest import mock

import hangups
import hangups.channel
import pytest
from aioresponses import aioresponses
from aioresponses.compat import merge_url_params

import hangupsbot.core
import hangupsbot.hangups_conversation
from tests.constants import DEFAULT_BOT_KWARGS
from tests.utils import build_user_conversation_list_base


NOOP = b'17\n[[1,["noop"]\n]\n]\n'
GSESSIONID = b'52\n[[0,["c","MYSID","",8]\n]\n,[1,[{"gsid":"MYGSID"}]]\n]\n'

LONG_POLLING_URL = hangups.channel.CHANNEL_URL
FETCH_CHANNEL_SID_PARAMS = {'VER': 8, 'RID': 81188, 'ctype': 'hangouts'}
FETCH_CHANNEL_SID_URL = merge_url_params(url=LONG_POLLING_URL,
                                         params=FETCH_CHANNEL_SID_PARAMS)
LONG_POLLING_REQUEST_PARAMS = {'VER': 8, 'RID': 'rpc', 't': 1, 'CI': 0,
                               'ctype': 'hangouts', 'TYPE': 'xmlhttp',
                               'gsessionid': 'MYGSID', 'SID': 'MYSID'}
LONG_POLLING_REQUEST_URL = merge_url_params(url=LONG_POLLING_URL,
                                            params=LONG_POLLING_REQUEST_PARAMS)

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
            lock = asyncio.Lock()
            await lock.acquire()
            await lock.acquire()  # delay further requests

    def _delete(path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    _delete(DEFAULT_BOT_KWARGS['config_path'])
    _delete(DEFAULT_BOT_KWARGS['memory_path'])
    with mock.patch('hangups.get_auth_stdin') as get_auth_stdin:
        get_auth_stdin.return_value = {'SAPISID': 'IS_REQUIRED'}

        with aioresponses() as aiohttp_mock:
            # hangups.channel.Channel._fetch_channel_sid
            aiohttp_mock.post(FETCH_CHANNEL_SID_URL, body=GSESSIONID)

            # hangups.channel.Channel._longpoll_request
            aiohttp_mock.get(LONG_POLLING_REQUEST_URL, body=NOOP)

            with mock.patch('hangups.build_user_conversation_list',
                            new=build_user_conversation_list):

                bot_ = _TestHangupsBot(**DEFAULT_BOT_KWARGS)
                bot_.config['plugins'] = ()
                with pytest.raises(SystemExit):
                    bot_.run()
