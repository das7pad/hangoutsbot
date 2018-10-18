"""test the module `hangupsbot.plugins`"""

import pytest

from hangupsbot import plugins


@pytest.mark.asyncio
async def test_load_protected_module_0(bot):
    with pytest.raises(plugins.Protected):
        await plugins.load(bot, 'plugins')


@pytest.mark.asyncio
async def test_load_protected_module_1(bot):
    with pytest.raises(plugins.Protected):
        await plugins.load(bot, 'commands')
