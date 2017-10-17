"""fixtures for testing"""

__all__ = (
    'module_wrapper',
)

import asyncio
import logging

import pytest

import hangupsbot.core
import hangupsbot.commands
import hangupsbot.plugins
import hangupsbot.sinks

from tests.constants import (
    EVENT_LOOP,
)

CLEANUP_LOOP = asyncio.new_event_loop()
logger = logging.getLogger('tests')

@pytest.fixture(scope='module', autouse=True)
def module_wrapper(request):
    def _cleanup():
        CLEANUP_LOOP.run_until_complete(hangupsbot.commands.command.clear())
        CLEANUP_LOOP.run_until_complete(hangupsbot.plugins.tracking.clear())
        CLEANUP_LOOP.run_until_complete(
            hangupsbot.sinks.aiohttp_servers.clear())
        hangupsbot.core.AsyncQueue.release_block()
        CLEANUP_LOOP.run_until_complete(EVENT_LOOP.shutdown_asyncgens())
        EVENT_LOOP.run_until_complete(asyncio.sleep(0.1))
    request.addfinalizer(_cleanup)
    logger.info('Loaded Module %s', request.module.__name__)
