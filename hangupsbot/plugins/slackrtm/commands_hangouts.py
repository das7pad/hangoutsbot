import logging

from .exceptions import (
    AlreadySyncingError,
    NotSyncingError,
)
from .storage import (
    SLACKRTMS,
)


logger = logging.getLogger(__name__)


async def slacks(bot, event, *args):
    """list all configured slack teams

       usage: /bot slacks"""

    lines = ["**Configured Slack teams:**"]

    for slackrtm in SLACKRTMS:
        lines.append("* {}".format(slackrtm.name))

    await bot.coro_send_message(event.conv_id, "\n".join(lines))

async def slack_channels(bot, event, *args):
    """list all slack channels available in specified slack team

    usage: /bot slack_channels <teamname>"""

    if len(args) != 1:
        await bot.coro_send_message(event.conv_id, "specify slack team to get list of channels")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    await slackrtm.update_cache('channels')
    await slackrtm.update_cache('groups')

    lines = ['<b>Channels:</b>', '<b>Private groups</b>']

    for channel in slackrtm.conversations:
        if slackrtm.conversations[channel].get('is_archived', True):
            # filter dms and archived channels/groups
            continue
        line = '- %s: %s' % (channel, slackrtm.get_chatname(channel))
        if channel[0] == 'C':
            lines.insert(1, line)
        else:
            lines.append(line)

    await bot.coro_send_message(event.conv_id, "\n".join(lines))


async def slack_users(bot, event, *args):
    """list all slack channels available in specified slack team

        usage: /bot slack_users <team> <channel>"""

    if len(args) != 2:
        await bot.coro_send_message(event.conv_id, "specify slack team and channel")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    await slackrtm.update_cache('channels')
    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    lines = ["**Slack users in channel {}**:".format(channelname)]

    users = await slackrtm.get_channel_users(channelid)
    for username, realname in sorted(users.items()):
        lines.append("* {} {}".format(username, realname))

    await bot.coro_send_message(event.conv_id, "\n".join(lines))


async def slack_listsyncs(bot, event, *args):
    """list current conversations we are syncing

    usage: /bot slack_listsyncs"""

    lines = ["**Currently synced:**"]

    for slackrtm in SLACKRTMS:
        for sync in slackrtm.syncs:
            hangoutname = bot.conversations.get_name(sync['hangoutid'], 'unknown')
            lines.append("{} : {} ({})\n  {} ({})\n".format(
                slackrtm.name,
                slackrtm.get_chatname(sync['channelid']),
                sync['channelid'],
                hangoutname,
                sync['hangoutid'],
                ))

    await bot.coro_send_message(event.conv_id, "\n".join(lines))


async def slack_syncto(bot, event, *args):
    """start syncing the current hangout to a given slack team/channel

    usage: /bot slack_syncto <teamname> <channelid>"""

    if len(args) != 2:
        await bot.coro_send_message(event.conv_id, "specify slack team and channel")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    try:
        slackrtm.config_syncto(channelid, event.conv_id)
    except AlreadySyncingError:
        await bot.coro_send_message(event.conv_id, "hangout already synced with {} : {}".format(slackname, channelname))
        return

    await bot.coro_send_message(event.conv_id, "this hangout synced with {} : {}".format(slackname, channelname))


async def slack_disconnect(bot, event, *args):
    """stop syncing the current hangout with given slack team and channel

    usage: /bot slack_disconnect <teamname> <channelid>"""

    if len(args) != 2:
        await bot.coro_send_message(event.conv_id, "specify slack team and channel")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    try:
        slackrtm.config_disconnect(channelid, event.conv.id_)
    except NotSyncingError:
        await bot.coro_send_message(event.conv_id, "current hangout not previously synced with {} : {}".format(slackname, channelname))
        return

    await bot.coro_send_message(event.conv_id, "this hangout disconnected from {} : {}".format(slackname, channelname))
