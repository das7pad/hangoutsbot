"""test the fixtures"""

# TODO(das7pad): more tests

import pytest
import hangupsbot.event

from hangupsbot import core, plugins, commands

from tests import simple_conv_list, CONV_ID_1, Message

# pylint:disable=redefined-outer-name

@pytest.mark.asyncio
async def test_bot(bot):
    """test the TestHangupsBot

    Args:
        bot (tests.fixtures.TestHangupsBot): current test instance
    """
    assert isinstance(bot, core.HangupsBot)

    # check mixins
    assert plugins.tracking.bot is bot
    assert plugins.tracking is commands.command.tracking

    assert all(conv_id in bot.conversations for conv_id in simple_conv_list)

    message = Message(CONV_ID_1, 'TEXT', {'key': 'VALUE'}, 0)
    await bot.coro_send_message(*message)
    assert bot.last_message == message


def test_event(event):
    """test the TestConversationEvent

    Args:
        event (tests.fixtures.TestConversationEvent): message wrapper
    """
    assert isinstance(event, hangupsbot.event.ConversationEvent)
    assert event.CHAT_ID == event.user_id.chat_id
    assert event.CONV_ID == event.conv_id

    event_with_text = event.with_text('my text')
    assert event_with_text.text == 'my text'

    event_with_args = event.for_command('my_cmd', 'first', 'second')
    assert event_with_args.text == '/bot my_cmd first second'
    args = event_with_args.args
    assert args[0] == 'first'
    assert args[1] == 'second'
