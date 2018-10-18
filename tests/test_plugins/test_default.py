"""test the `hangupsbot.plugins.default` module"""

# TODO(das7pad): `broadcast`, `config` and `user` require refactored methods
# TODO(das7pad): `quit` may use `tests.test_core.test_core.test_hangupsbot_run`
# TODO(das7pad): `rename` and `leave` require a mocked hangups client
# TODO(das7pad): `hangouts` requires `permamem` tested
# TODO(das7pad): `users`, `rename` and `leave` require `commands.convid` tested


import asyncio

import pytest

from hangupsbot import (
    commands,
    plugins,
)
from tests import (
    run_cmd,
    simple_conv_list,
    simple_user_list,
)
from tests.constants import (
    CHAT_ID_ADMIN,
    CONV_ID_3,
)


@pytest.mark.asyncio
async def test_load_plugin(bot):
    await plugins.load(bot, 'plugins.default')


@pytest.mark.asyncio
async def test_echo(bot, event):
    event = event.with_text('/bot echo')
    with pytest.raises(commands.Help):
        await run_cmd(bot, event)

    text = 'ONE TWO'
    event = event.for_command('echo', text)
    result = await run_cmd(bot, event)
    assert (event.CONV_ID, text) == result

    request = '%s %s' % (CONV_ID_3, text)
    event = event.for_command('echo', request)
    result = await run_cmd(bot, event)
    if event.CHAT_ID == CHAT_ID_ADMIN:
        expected = (CONV_ID_3, text)
    else:
        expected_text = '<b>only admins can echo other conversations</b>'
        expected = (event.CONV_ID, expected_text)
    assert expected == result


@pytest.mark.asyncio
async def test_reload(bot, event):
    """test `/bot reload`

    Args:
        bot (tests.fixtures.TestHangupsBot): current test instance
        event (tests.fixtures.TestConversationEvent): message wrapper
    """

    def on_reload_config():
        reloaded.append('config')

    def on_reload_memory():
        reloaded.append('memory')

    reloaded = []
    bot.config.on_reload.add_observer(on_reload_config)
    bot.memory.on_reload.add_observer(on_reload_memory)
    event = event.for_command('reload')
    await run_cmd(bot, event)
    await asyncio.sleep(0)
    assert 'reloading' in bot.last_message.text
    bot.config.on_reload.remove_observer(on_reload_config)
    bot.memory.on_reload.remove_observer(on_reload_memory)
    assert reloaded == ['config', 'memory']


@pytest.mark.asyncio
async def test_whereami(bot, event):
    event = event.for_command('whereami')
    result = await run_cmd(bot, event)
    assert event.CONV_ID in result
    assert simple_conv_list.get_name(event.CONV_ID) in result


@pytest.mark.asyncio
async def test_whoami(bot, event):
    path = ['user_data', event.CHAT_ID, 'label']
    if bot.memory.exists(path):
        bot.memory.pop_by_path(path)

    event = event.for_command('whoami')
    result = await run_cmd(bot, event)
    assert simple_user_list.get_name(event.CHAT_ID) in result
    assert event.CHAT_ID in result

    label = 'LABEL'
    bot.memory.set_by_path(path, label)

    result = await run_cmd(bot, event)
    assert label in result
    assert event.CHAT_ID in result
