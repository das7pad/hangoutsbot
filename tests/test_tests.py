"""test the fixtures"""

# TODO(das7pad): more tests

import hangupsbot.event
from hangupsbot import core, plugins, commands, handlers

from tests import simple_conv_list

# pylint:disable=redefined-outer-name

def test_bot(bot):
    assert isinstance(bot, core.HangupsBot)

    # check mixins
    assert plugins.tracking.bot is bot
    assert plugins.tracking is commands.command.tracking

    assert all(conv_id in bot.conversations for conv_id in simple_conv_list)

def test_event(event):
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
