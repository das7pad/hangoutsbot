"""test the `hangupsbot.plugins.convtools_invitations` module"""

# TODO(das7pad): test the commands and event handler

import asyncio
import time

import pytest

from hangupsbot import (
    plugins,
)

from hangupsbot.plugins import (
    convtools_invitations,
)


def test_cleanup_common(bot):
    invites = {
        'ABC': {
            'expiry': 123,
        },
        'CDE': {
            'expiry': time.time() + 60,
        }
    }
    bot.memory.set_by_path(['invites'], invites)

    count = convtools_invitations._perform_cleanup(bot)
    assert count == 1
    assert 'ABC' not in invites
    assert 'CDE' in invites


def test_cleanup_missing_invites(bot):
    bot.memory.set_by_path(['invites'], {})
    bot.memory.pop_by_path(['invites'])

    count = convtools_invitations._perform_cleanup(bot)
    assert count == 0


def test_cleanup_broken_invites(bot):
    invites = []
    bot.memory.set_by_path(['invites'], invites)

    count = convtools_invitations._perform_cleanup(bot)
    assert count == 0


def test_cleanup_broken_invite1(bot):
    invites = {
        'ABC': [],
    }
    bot.memory.set_by_path(['invites'], invites)

    count = convtools_invitations._perform_cleanup(bot)
    assert count == 1
    assert 'ABC' not in invites


def test_cleanup_broken_invite2(bot):
    invites = {
        'ABC': {},
    }
    bot.memory.set_by_path(['invites'], invites)

    count = convtools_invitations._perform_cleanup(bot)
    assert count == 1
    assert 'ABC' not in invites


def test_cleanup_broken_invite3(bot):
    invites = {
        'ABC': {
            'expiry': 'XYZ',
        },
    }
    bot.memory.set_by_path(['invites'], invites)

    count = convtools_invitations._perform_cleanup(bot)
    assert count == 1
    assert 'ABC' not in invites


@pytest.mark.asyncio
async def test_cleanup_task1(bot):
    invites = {
        'ABC': {
            'expiry': 123,
        },
        'CDE': {
            'expiry': time.time() + 60,
        }
    }
    bot.memory.set_by_path(['invites'], invites)

    task = asyncio.ensure_future(
        convtools_invitations.cleanup_periodically(
            bot,
        )
    )
    await asyncio.sleep(0)
    assert 'ABC' not in invites
    assert 'CDE' in invites
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert task.done()
    assert task.result() is None


@pytest.mark.asyncio
async def test_cleanup_task2(bot):
    invites = {
        'ABC': {
            'expiry': 123,
        },
        'CDE': {
            'expiry': time.time() + 60,
        }
    }
    bot.memory.set_by_path(['invites'], invites)

    task = plugins.start_asyncio_task(
        convtools_invitations.cleanup_periodically
    )
    await asyncio.sleep(0)
    assert 'ABC' not in invites
    assert 'CDE' in invites
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert task.done()
    assert task.result() is None
