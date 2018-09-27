"""test hangupsbot.commands.plugincontrol`"""

import pytest

from hangupsbot import plugins

from tests import run_cmd


@pytest.mark.asyncio
async def test_load_plugin(bot):
    await plugins.load(bot, 'commands.plugincontrol')


@pytest.mark.asyncio
async def test_pluginload(bot, event):
    event = event.with_text('/bot pluginload')
    await run_cmd(bot, event)
    assert 'module path required' in bot.last_message.text

    event = event.with_text('/bot pluginload plugins')
    await run_cmd(bot, event)
    assert 'protected' in bot.last_message.text

    event = event.with_text('/bot pluginload plugins.default')
    await run_cmd(bot, event)
    assert '<b>loaded</b>' in bot.last_message.text

    event = event.with_text('/bot pluginload plugins.default')
    await run_cmd(bot, event)
    assert 'already loaded' in bot.last_message.text

    # cleanup
    await plugins.unload(bot, 'plugins.default')

    event = event.with_text('/bot pluginload plugins.<invalid>')
    await run_cmd(bot, event)
    assert 'failed' in bot.last_message.text
