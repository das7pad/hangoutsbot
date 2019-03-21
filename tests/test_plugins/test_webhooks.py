"""test the webhook plugin"""

import asyncio
from unittest import mock

import aiohttp
import pytest

from hangupsbot.plugins import webhook
from hangupsbot.sync.event import SyncReply, SyncEvent
from hangupsbot.sync.image import SyncImage
from hangupsbot.sync.parser import MessageSegment
from hangupsbot.sync.user import SyncUser

# run all tests in an event loop
pytestmark = pytest.mark.asyncio


async def test_config_check():
    assert 'config type' in webhook._check_config('INVALID')

    assert 'missing' in webhook._check_config({})

    assert 'params' in webhook._check_config(
        {
            'url': 'http://example.com',
            'params': 'INVALID',
        }
    )

    assert webhook._check_config(
        {
            'url': 'http://example.com',
        }
    ) is None

    assert webhook._check_config(
        {
            'url': 'http://example.com',
            'params': {},
        }
    ) is None


async def test_global_config_check():
    assert webhook._get_valid_web_hooks('INVALID') == {}

    assert 'demo' not in webhook._get_valid_web_hooks(
        {
            'demo': 'INVALID',
        }
    )

    assert 'demo' in webhook._get_valid_web_hooks(
        {
            'demo': {
                'url': 'http://example.com',
            },
        }
    )

    assert'demo' in webhook._get_valid_web_hooks(
        {
            'demo': {
                'url': 'http://example.com',
                'params': {},
            },
        }
    )


async def test_segments_serialize_bold():
    segments = MessageSegment.from_str('<b>BOLD</b>')
    expected = [
        {
            'text': 'BOLD',
            'is_bold': True,
            'is_italic': False,
            'link_target': None,
        },
    ]

    actual = webhook.Handler.serialize_segments(segments)
    assert actual == expected


async def test_segments_serialize_multiline():
    segments = MessageSegment.from_str('MULTILINE\nTEXT')
    expected = [
        {
            'text': 'MULTILINE',
            'is_bold': False,
            'is_italic': False,
            'link_target': None,
        },
        {
            'text': '\n',
            'is_bold': False,
            'is_italic': False,
            'link_target': None,
        },
        {
            'text': 'TEXT',
            'is_bold': False,
            'is_italic': False,
            'link_target': None,
        }
    ]

    actual = webhook.Handler.serialize_segments(segments)
    assert actual == expected


async def test_reply_serialize(bot):
    user_identifier = 'platform:USER'
    full_name = 'FULL NAME'
    text = 'MULTILINE\nTEXT'
    offset = 30

    user = SyncUser(
        identifier=user_identifier,
        user_name=full_name,
    )

    reply = SyncReply(
        identifier='platform:CHAT',
        user=user,
        text=text,
        offset=offset,
    )

    actual = webhook.Handler.serialize_reply(reply)
    expected = {
        'offset': offset,
        'user_identifier': user_identifier,
        'user_name': full_name,
        'text': text,
    }
    assert actual == expected


async def test_event_serialize(bot):
    chat_identifier = 'platform:CHAT'
    conv_id = 'CONV_ID'

    user_identifier = 'platform:USER'
    full_name = 'FULL NAME'

    edited = True
    text = 'MULTILINE\nTEXT'
    segments = webhook.Handler.serialize_segments(MessageSegment.from_str(text))

    reply_text = 'REPLY\nMULTILINE\nTEXT'
    offset = 30

    image_type = 'photo'
    image_url = 'http://example.com/image.jpg'

    image = SyncImage(
        type_=image_type,
        url=image_url,
        cache=90,
    )

    user = SyncUser(
        identifier=user_identifier,
        user_name=full_name,
    )

    reply = SyncReply(
        identifier=chat_identifier,
        user=user,
        text=reply_text,
        offset=offset,
    )

    event = SyncEvent(
        identifier=chat_identifier,
        user=user,
        edited=edited,
        text=text,
        conv_id=conv_id,
        reply=reply,
        image=image,
    )

    with mock.patch('hangupsbot.sync.event.SyncEvent.get_image_url') as patched:
        patched.return_value = asyncio.Future()
        patched.return_value.set_result(image_url)

        actual = await webhook.Handler.serialize_event(event)

    expected = {
        'conv_id': conv_id,
        'edited': edited,
        'image_type': image_type,
        'image_url': image_url,
        'reply': {
            'offset': offset,
            'user_identifier': user_identifier,
            'user_name': full_name,
            'text': reply_text,
        },
        'segments': segments,
        'text': text,
        'user_identifier': user_identifier,
        'user_name': full_name,
    }

    assert actual == expected


async def test_event_serialize_no_reply(bot):
    chat_identifier = 'platform:CHAT'
    conv_id = 'CONV_ID'

    user_identifier = 'platform:USER'
    full_name = 'FULL NAME'

    edited = True
    text = 'MULTILINE\nTEXT'
    segments = webhook.Handler.serialize_segments(MessageSegment.from_str(text))

    image_type = 'photo'
    image_url = 'http://example.com/image.jpg'

    image = SyncImage(
        type_=image_type,
        url=image_url,
        cache=90,
    )

    user = SyncUser(
        identifier=user_identifier,
        user_name=full_name,
    )

    event = SyncEvent(
        identifier=chat_identifier,
        user=user,
        edited=edited,
        text=text,
        conv_id=conv_id,
        image=image,
    )

    with mock.patch('hangupsbot.sync.event.SyncEvent.get_image_url') as patched:
        patched.return_value = asyncio.Future()
        patched.return_value.set_result(image_url)

        actual = await webhook.Handler.serialize_event(event)

    expected = {
        'conv_id': conv_id,
        'edited': edited,
        'image_type': image_type,
        'image_url': image_url,
        'reply': {},
        'segments': segments,
        'text': text,
        'user_identifier': user_identifier,
        'user_name': full_name,
    }

    assert actual == expected


async def test_session_setup(bot):
    handler = webhook.Handler(
        name='NAME',
        target='http://example.com/target',
        params={},
    )

    await handler._set_session()
    assert handler._session._default_headers == webhook.DEFAULT_HEADER


async def test_session_setup_custom_header(bot):
    headers = {
        'X-Tested-By': 'me',
    }
    handler = webhook.Handler(
        name='NAME',
        target='http://example.com/target',
        params={
            'headers': headers
        },
    )

    await handler._set_session()
    actual = handler._session._default_headers
    expected = headers.copy()
    headers.update(webhook.DEFAULT_HEADER)

    assert actual == expected


async def test_source_filter(bot):
    handler = webhook.Handler(
        name='NAME',
        target='http://example.com/target',
        params={},
    )

    event = SyncEvent(
        identifier='X:1',
        user=SyncUser(identifier='Y:1', user_name='Z'),
        text='',
        conv_id='CONV',
    )

    send_message = 'hangupsbot.plugins.webhook.Handler.send_message'

    with mock.patch(send_message) as send:  # type: mock.MagicMock
        send.return_value = asyncio.Future()
        send.return_value.set_result(None)

        await handler._handle_message(bot, event)

        assert send.call_count == 0


async def test_source_match(bot):
    handler_name = 'NAME'
    handler = webhook.Handler(
        name=handler_name,
        target='http://example.com/target',
        params={},
    )

    source = 'X:1'

    event = SyncEvent(
        identifier=source,
        user=SyncUser(identifier='Y:1', user_name='Z'),
        text='',
        conv_id='CONV',
    )

    bot.memory.set_by_path(['webhook', handler_name], [source])

    send_message = 'hangupsbot.plugins.webhook.Handler.send_message'

    with mock.patch(send_message) as send:  # type: mock.MagicMock
        send.return_value = asyncio.Future()
        send.return_value.set_result(None)

        await handler._handle_message(bot, event)

        assert send.call_count == 1


async def test_send(bot):
    target = 'http://example.com/target'
    params = {
        'param1': 'VAL'
    }
    handler = webhook.Handler(
        name='NAME',
        target=target,
        params=params,
    )

    handler._session = mock.MagicMock()
    post = mock.MagicMock()
    handler._session.post = post

    return_value = asyncio.Future()
    return_value.set_result(None)
    handler._session.post.return_value = return_value

    message = {}

    await handler.send(message)

    post.assert_called_with(
        target, json=message, **params
    )


async def test_send_error_handling(bot):
    handler = webhook.Handler(
        name='NAME',
        target='http://example.com/target',
        params={},
    )

    handler._session = mock.MagicMock()
    post = mock.MagicMock()
    handler._session.post = post

    return_value = asyncio.Future()
    return_value.set_exception(aiohttp.ClientError())
    handler._session.post.return_value = return_value

    message = {}

    await handler.send(message)


async def test_send_cancelled(bot):
    handler = webhook.Handler(
        name='NAME',
        target='http://example.com/target',
        params={},
    )

    handler._session = mock.MagicMock()
    post = mock.MagicMock()
    handler._session.post = post

    return_value = asyncio.Future()
    return_value.cancel()
    handler._session.post.return_value = return_value

    message = {}

    with pytest.raises(asyncio.CancelledError):
        await handler.send(message)
