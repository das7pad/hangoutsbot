"""test the `hangupsbot.plugins.forwarding` module"""

import pytest

from hangupsbot import (
    commands,
    plugins,
)
from tests import (
    run_cmd,
    simple_conv_list,
)
from tests.constants import (
    CHAT_ID_ADMIN,
    CONV_ID_3,
    CONV_NAME_3,
)


@pytest.mark.asyncio
async def test_load_plugin(bot):
    await plugins.load(bot, 'commands.alias')
    await plugins.load(bot, 'plugins.forwarding')


@pytest.mark.asyncio
async def test_forward_to(bot, event):
    if event.CHAT_ID != CHAT_ID_ADMIN:
        # admin only command
        return

    event = event.with_text('/bot forward_to')
    with pytest.raises(commands.Help):
        # missing arg
        await run_cmd(bot, event)

    path = ['conversations', event.CONV_ID, 'forward_to']

    args = (CONV_ID_3,)
    event = event.for_command('forward_to', *args)
    result = await run_cmd(bot, event)
    assert CONV_NAME_3 in result
    assert 'Added' in result
    assert CONV_ID_3 in bot.config.get_by_path(path)

    args = (CONV_ID_3,)
    event = event.for_command('forward_to', *args)
    result = await run_cmd(bot, event)
    assert CONV_NAME_3 in result
    assert 'Removed' in result
    assert CONV_ID_3 not in bot.config.get_by_path(path)

    args = (event.CONV_ID,)
    event = event.for_command('forward_to', *args)
    result = await run_cmd(bot, event)
    assert simple_conv_list.get_name(event.CONV_ID) in result
    assert 'Loop blocked' in result
    assert event.CONV_ID not in bot.config.get_by_path(path)

    invalid_id = 'INVALID'
    args = (invalid_id,)
    event = event.for_command('forward_to', *args)
    result = await run_cmd(bot, event)
    assert invalid_id in result
    assert 'Unknown chat' in result
    assert invalid_id not in bot.config.get_by_path(path)
