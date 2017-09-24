from commands import Help

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


def _get_slackrtm(slackname):
    """scan all running slackrtms for a matching name

    Args:
        slackname (str): user input as a search query

    Returns:
        core.SlackRTM: the requested team instance

    Raises:
        Help: no or multiple SlackRTMs match the seach query
    """
    matches = []
    for slackrtm in SLACKRTMS:
        if slackname in slackrtm.name:
            matches.append(slackrtm)
    if len(matches) == 1:
        return matches[0]
    elif matches:
        raise Help(_('these slack teams match "%s", be more specific!') %
                   (slackname, ', '.join([slackrtm.name
                                          for slackrtm in matches])))
    raise Help(_('there is no slack team with name "%s", use <i>{bot_cmd} '
                 'slacks</i> to list all teams') % slackname)

def _get_slackrtm_and_channel(slackname, channel):
    """scan all running slackrtms and their channel for a match

    Args:
        slackname (str): seach query for a slack team/SlackRTM
        channel (str): channel id of the team specified with slackname

    Returns:
        tuple: `(<core.SlackRTM>, <str>)`, requested team instance and channel

    Raises:
        Help: no matching slackrtm or channel is not in slackrtm
    """
    slackrtm = _get_slackrtm(slackname)
    channelname = slackrtm.get_chatname(channel)
    if channelname is not None:
        return slackrtm, channelname

    raise Help(_('there is no channel with name "%s" in "%s", use '
                 '<i>{bot_cmd} slack_channels %s</i> to list all channels') %
               (channel, slackname, slackname))


def slacks(*dummys):
    """list all configured slack teams

       usage: /bot slacks"""
    lines = ['<b>Configured Slack teams:</b>']

    for slackrtm in SLACKRTMS:
        lines.append('- {}'.format(slackrtm.name))

    return '\n'.join(lines)

async def slack_channels(dummy0, dummy1, *args):
    """list all slack channels available in specified slack team

    usage: /bot slack_channels <teamname>"""
    if len(args) != 1:
        raise Help('specify slack team to get list of channels')

    slackrtm = _get_slackrtm(args[0])
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

    return '\n'.join(lines)

def slack_users(dummy0, dummy1, *args):
    """list all slack channels available in specified slack team

        usage: /bot slack_users <team> <channel>"""
    if len(args) != 2:
        raise Help(_('specify slack team and channel'))

    slackname = args[0]
    channel = args[1]
    slackrtm, channelname = _get_slackrtm_and_channel(slackname, channel)

    lines = ['<b>Slack users in channel {}</b>:'.format(channelname)]

    users = slackrtm.get_channel_users(channel)
    for username, realname in sorted(users.items()):
        lines.append('- @{}: {}'.format(username, realname))

    return '\n'.join(lines)

def slack_listsyncs(bot, *dummys):
    """list current conversations we are syncing

    usage: /bot slack_listsyncs"""
    lines = ['<b>Currently synced:</b>']

    for slackrtm in SLACKRTMS:
        for sync in slackrtm.syncs:
            hangoutname = bot.conversations.get_name(sync['hangoutid'],
                                                     'unknown')
            lines.append('{} : {} ({})\n  {} ({})\n'.format(
                slackrtm.name,
                slackrtm.get_chatname(sync['channelid']),
                sync['channelid'],
                hangoutname,
                sync['hangoutid']))

    return '\n'.join(lines)

def slack_syncto(dummy, event, *args):
    """start syncing the current hangout to a given slack team/channel

    usage: /bot slack_syncto <teamname> <channelid>"""
    if len(args) != 2:
        raise Help('specify only slack team and channel')

    slackname = args[0]
    channel = args[1]
    slackrtm, channelname = _get_slackrtm_and_channel(slackname, channel)

    try:
        slackrtm.config_syncto(channel, event.conv_id)
    except AlreadySyncingError:
        return _('hangout already synced with %s:%s') % (slackname, channelname)

    return 'this hangout synced with {}:{}'.format(slackname, channelname)

def slack_disconnect(dummy, event, *args):
    """stop syncing the current hangout with given slack team and channel

    usage: /bot slack_disconnect <teamname> <channelid>"""
    if len(args) != 2:
        raise Help('specify slack team and channel')

    slackname = args[0]
    channel = args[1]
    slackrtm, channelname = _get_slackrtm_and_channel(slackname, channel)

    try:
        slackrtm.config_disconnect(channel, event.conv_id)
    except NotSyncingError:
        return _('current hangout not previously synced with {}:{}').format(
            slackname, channelname)

    return 'this hangout disconnected from {}:{}'.format(slackname, channelname)
