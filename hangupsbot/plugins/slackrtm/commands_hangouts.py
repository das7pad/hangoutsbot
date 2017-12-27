"""hangouts commands to setup/remove/manage slackrtm syncs"""

from hangupsbot.commands import Help

from .exceptions import (
    AlreadySyncingError,
    NotSyncingError,
)
from .storage import (
    SLACKRTMS,
)


HELP = {
    'slack_syncto': _('start syncing the current hangout to a given slack '
                      'team/channel\n    '
                      'usage: {bot_cmd} slack_syncto <teamname> <channelid>'),
    'slack_disconnect': _('stop syncing the current hangout with a given slack '
                          'team and channel\n    usage: '
                          '{bot_cmd} slack_disconnect <teamname> <channelid>'),
    'slack_listsyncs': _('list current conversations we are syncing\n'
                         '    usage: {bot_cmd} slack_listsyncs'),
    'slack_channels': _('list all slack channels available in a specified slack'
                        'team\n    usage: {bot_cmd} slack_channels <teamname>'),
    'slacks': _('list all configured slack teams\n'
                '    usage: {bot_cmd} slacks'),
    'slack_users': _('list all slack users in a specified slack channel'
                     'team\n    usage: {bot_cmd} slack_users <team> <channel>'),
}


def _get_slackrtm(bot, slack_name):
    """scan all running slackrtms for a matching name

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        slack_name (str): user input as a search query

    Returns:
        core.SlackRTM: the requested team instance

    Raises:
        Help: no or multiple SlackRTMs match the search query
    """
    matches = []
    for slackrtm in SLACKRTMS:
        if slack_name in slackrtm.name:
            matches.append(slackrtm)
    if len(matches) == 1:
        return matches[0]
    elif matches:
        raise Help(_('these slack teams match "%s", be more specific!') %
                   (slack_name, ', '.join([slackrtm.name
                                           for slackrtm in matches])))
    raise Help(_('there is no slack team with name "{slack_name}", use '
                 '<i>{bot_cmd} slacks</i> to list all teams').format(
                     bot_cmd=bot.command_prefix,
                     slack_name=slack_name))

def _get_slackrtm_and_channel(bot, slack_name, channel):
    """scan all running slackrtms and their channel for a match

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        slack_name (str): search query for a slack team/SlackRTM
        channel (str): channel id of the team specified with `slack_name`

    Returns:
        tuple[core.SlackRTM, str]: requested team instance and channel id

    Raises:
        Help: no matching slackrtm or channel is not in slackrtm
    """
    slackrtm = _get_slackrtm(bot, slack_name)
    channel_name = slackrtm.get_chatname(channel)
    if channel_name is not None:
        return slackrtm, channel_name

    raise Help(_('there is no channel with name "{channel}" in "{slack_name}", '
                 'use <i>{bot_cmd} slack_channels {slack_name}</i> to list all '
                 'channels').format(channel=channel, slack_name=slack_name,
                                    bot_cmd=bot.command_prefix))


def slacks(*dummys):
    """list all configured slack teams

    Args:
        dummys (mixed): ignored

    Returns:
        str: command output
    """
    lines = ['<b>Configured Slack teams:</b>']

    for slackrtm in SLACKRTMS:
        lines.append('- {}'.format(slackrtm.name))

    return '\n'.join(lines)

async def slack_channels(bot, dummy, *args):
    """list all slack channels available in specified slack team

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        dummy (hangupsbot.event.ConversationEvent): ignored
        args (str): the slackrtm name to query channels from

    Returns:
        str: command output

    Raises:
        Help: invalid request
    """
    if len(args) != 1:
        raise Help('specify slack team to get list of channels')

    slackrtm = _get_slackrtm(bot, args[0])
    await slackrtm.update_cache('channels')
    await slackrtm.update_cache('groups')

    lines = ['<b>Channels:</b>', '<b>Private groups</b>']
    for channel in slackrtm.conversations:
        if slackrtm.conversations[channel].get('is_archived', True):
            # covers archived channels/groups and ims
            continue
        line = '- %s: %s' % (channel, slackrtm.get_chatname(channel))
        if channel[0] == 'C':
            lines.insert(1, line)
        else:
            lines.append(line)

    return '\n'.join(lines)

def slack_users(bot, dummy, *args):
    """list all slack channels available in specified slack team

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        dummy (hangupsbot.event.ConversationEvent): ignored
        args (str): slackrtm name and a channel of it

    Returns:
        str: command output

    Raises:
        Help: invalid request
    """
    if len(args) != 2:
        raise Help(_('specify slack team and channel'))

    slackname = args[0]
    channel = args[1]
    slackrtm, channel_name = _get_slackrtm_and_channel(bot, slackname, channel)

    lines = ['<b>Slack users in channel {}</b>:'.format(channel_name)]

    users = slackrtm.get_channel_users(channel)
    for username, real_name in sorted(users.items()):
        lines.append('- @{}: {}'.format(username, real_name))

    return '\n'.join(lines)

def slack_listsyncs(bot, *dummys):
    """list current conversations we are syncing

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        dummys (mixed): ignored

    Returns:
        str: command output
    """
    lines = ['<b>Currently synced:</b>']

    for slackrtm in SLACKRTMS:
        for sync in slackrtm.syncs:
            hangout_name = bot.conversations.get_name(sync['hangoutid'],
                                                      'unknown')
            lines.append('{} : {} ({})\n  {} ({})\n'.format(
                slackrtm.name,
                slackrtm.get_chatname(sync['channelid']),
                sync['channelid'],
                hangout_name,
                sync['hangoutid']))

    return '\n'.join(lines)

def slack_syncto(bot, event, *args):
    """start syncing the current hangout to a given slack team/channel

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): slackrtm name and a channel of it

    Returns:
        str: command output

    Raises:
        Help: invalid request
    """
    if len(args) != 2:
        raise Help('specify only slack team and channel')

    slackname = args[0]
    channel = args[1]
    slackrtm, channel_name = _get_slackrtm_and_channel(bot, slackname, channel)

    try:
        slackrtm.config_syncto(channel, event.conv_id)
    except AlreadySyncingError:
        return _('hangout already synced with {teamname}:{channel}').format(
            teamname=slackname, channel=channel_name)

    return 'this hangout synced with {}:{}'.format(slackname, channel_name)

def slack_disconnect(bot, event, *args):
    """stop syncing the current hangout with given slack team and channel

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): slackrtm name and a channel of it

    Returns:
        str: command output

    Raises:
        Help: invalid request
    """
    if len(args) != 2:
        raise Help('specify slack team and channel')

    slackname = args[0]
    channel = args[1]
    slackrtm, channel_name = _get_slackrtm_and_channel(bot, slackname, channel)

    try:
        slackrtm.config_disconnect(channel, event.conv_id)
    except NotSyncingError:
        return _('current hangout not previously synced with {}:{}').format(
            slackname, channel_name)

    return 'this hangout disconnected from {}:{}'.format(slackname, channel_name)
