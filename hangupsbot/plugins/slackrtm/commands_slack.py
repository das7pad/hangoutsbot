"""commands that can be issued from the slack part of slackrtm"""

import asyncio
import logging
import sys

from .exceptions import (
    AlreadySyncingError,
    IgnoreMessage,
    NotSyncingError,
)
from .user import SlackUser


_IGNORE_COMMAND_MESSAGE = IgnoreMessage('message is command')

logger = logging.getLogger(__name__)


async def slack_command_handler(slack_bot, msg):
    """parse the message text and run the command of a message

    Args:
        slack_bot (core.SlackRTM): a running instance
        msg (message.SlackMessage): the currently handled instance

    Raises:
        IgnoreMessage: do not sync the message as it is a slack-only command
    """
    if not msg.user.usr_id:
        # do not respond to messages that originate from outside slack
        return

    tokens = msg.text.strip().split()

    if (len(tokens) < 2
            or tokens.pop(0).lower() not in slack_bot.command_prefixes):
        logger.debug('message is not a command')
        return

    command = tokens.pop(0).lower()
    args = tokens

    if command not in COMMANDS_USER and command not in COMMANDS_ADMIN:
        response = '@{}: {} is not recognised'.format(msg.user.username,
                                                      command)

    elif command in COMMANDS_ADMIN and msg.user.usr_id not in slack_bot.admins:
        response = '@{}: {} is an admin-only command'.format(msg.user.username,
                                                             command)

    else:
        func = getattr(sys.modules[__name__], command)
        response = func(slack_bot, msg, args)
        if asyncio.iscoroutinefunction(func):
            response = await response
        logger.debug('command %r returned %r', command, response)

    if isinstance(response, str):
        text = response
        channel = msg.channel

    elif isinstance(response, tuple):
        channel, text = response
        if channel == '1on1':
            channel = await slack_bot.get_slack1on1(msg.user.usr_id)

    else:
        # response from command that should not be send
        raise _IGNORE_COMMAND_MESSAGE

    slack_bot.send_message(channel=channel, text=text)
    raise _IGNORE_COMMAND_MESSAGE


# command access

COMMANDS_USER = [
    'help',
    'whereami',
    'whoami',
    'whois',
    'admins',
    'syncprofile',
    'unsyncprofile',
]
COMMANDS_ADMIN = [
    'hangouts',
    'listsyncs',
    'syncto',
    'disconnect',
    'chattitle',
    'sync_config',
]

# command help

HELP = {
    'help': _('display command help for a single or all commands\n'
              'usage: help [command]'),
    'whereami': _('tells you the current channel/group id'),
    'whoami': _('tells you your own user id'),
    'whois': _('*whois @username* tells you the user id of @username'),
    'admins': _('lists the slack users with admin privileges'),
    'syncprofile': _('start the process to sync your slack profile with a '
                     'G+ profile'),
    'unsyncprofile': _('detach the slack profile from a previously attached '
                       'G+ profile'),
    'hangouts': _('list all conversation the bot is participant in'),
    'listsyncs': _('lists all running sync connections'),
    'syncto': _('sync messages from the current channel/group to a '
                'specified hangout\n'
                'usage: syncto <hangout conversation id>'),
    'disconnect': _('stop syncing messages from the current '
                    'channel/group to the specified hangout\n'
                    'usage: disconnect <hangout conversation id>'),
    'chattitle': _('update the synced chattitle for the current or specified '
                   'channel'),
    'sync_config': _('update a config entry for the current or given channel'),
}


# command definitions

def help(slack_bot, msg, args):  # pylint:disable=redefined-builtin
    """list help for all available commands or query a single commands help

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        args (tuple[str]): additional arguments as strings

    Returns:
        tuple[str]: the channel target and the command output
    """
    if args and (args[0] in COMMANDS_USER or args[0] in COMMANDS_ADMIN):
        command = args[0].lower()
        return '1on1', '*%s*: %s' % (command, HELP[command])

    lines = ['*user commands:*']

    for command in COMMANDS_USER:
        lines.append('- *{}*: {}'.format(command, HELP[command]))

    if msg.user.usr_id in slack_bot.admins:
        lines.append('*admin commands:*')
        for command in COMMANDS_ADMIN:
            lines.append('- *{}*: {}'.format(command, HELP[command]))

    return '1on1', '\n\n'.join(lines)


def whereami(dummy, msg, dummys):
    """tells you the current channel/group id

    Args:
        dummy (core.SlackRTM): ignored
        msg (message.SlackMessage): the currently handled message
        dummys (tuple[str]): ignored

    Returns:
        str: command output
    """
    return _('@{user_name}: you are in channel {channel_id}').format(
        user_name=msg.user.username, channel_id=msg.channel)


def whoami(dummy, msg, dummys):
    """tells you your own user id

    Args:
        dummy (core.SlackRTM): ignored
        msg (message.SlackMessage): the currently handled message
        dummys (tuple[str]): ignored

    Returns:
        tuple[str]: the channel target and the command output
    """
    return '1on1', _('@{user_name}: your userid is {user_id}').format(
        user_name=msg.user.username, user_id=msg.user.usr_id)


def whois(slack_bot, msg, args):
    """whois @username tells you the user id of @username

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        args (tuple[str]): additional arguments as strings

    Returns:
        tuple[str]: the channel target and the command output
    """
    if not args:
        return '1on1', _('%s: sorry, but you have to specify a username for '
                         'command `whois`') % msg.user.username

    search = args[0][1:] if args[0][0] == '@' else args[0]
    for uid in slack_bot.users:
        if slack_bot.get_username(uid) == search:
            message = _('@{user_name}: the user id of _{name}_ is {other_id}'
                        ).format(user_name=msg.user.username,
                                 name=slack_bot.get_username(uid),
                                 other_id=uid)
            break
    else:
        message = _('@{user_name}: sorry, but I could not find user _{search}_ '
                    'in this slack.').format(user_name=msg.user.username,
                                             search=search)
    return '1on1', message


def admins(slack_bot, msg, dummys):
    """lists the slack users with admin privileges

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        dummys (tuple[str]): ignored

    Returns:
        tuple[str]: the channel target and the command output
    """
    message = ['<@%s>: my admins are:' % msg.user.usr_id]
    for admin in slack_bot.admins:
        user = SlackUser(slack_bot, channel=msg.channel, user_id=admin)
        message.append('<@%s> - %s' % (admin, user.full_name))

    return '1on1', '\n'.join(message)


async def syncprofile(slack_bot, msg, dummys):
    """start the process to sync your slack profile with a G+profile

    Args:
        slack_bot (core.SlackRTM): a running instance
        msg (message.SlackMessage): the currently handled instance
        dummys (tuple[str]): ignored

    Returns:
        tuple[str]: the channel target and the command output
    """
    bot = slack_bot.bot
    user_id = msg.user.usr_id
    path = ['profilesync', slack_bot.identifier]

    if bot.memory.exists(path + ['2ho', user_id]):
        text = _('Your profile is already linked to a G+Profile, use '
                 '*<@{name}> unsyncprofile* to unlink your profiles'
                 ).format(name=slack_bot.my_uid)
        return '1on1', text

    if bot.memory.exists(path + ['pending_2ho', user_id]):
        text = _('* [ REMINDER ] *\n')
        token = bot.memory.get_by_path(
            path + ['pending_2ho', user_id])

    else:
        text = ''
        token = bot.sync.start_profile_sync(slack_bot.identifier, user_id)

    bot_cmd = bot.command_prefix
    messages = [text + _(
        '*Please send me one of the messages below* '
        '<https://hangouts.google.com/chat/person/{bot_id}|in Hangouts>:\n'
        'Note: The message must start with *{bot_cmd}*, otherwise I do '
        'not process your message as a command and ignore your message.'
        '\nOur private Hangout and this chat will be automatically '
        'synced. You can then receive mentions and other messages I '
        'only send to private Hangouts. Use _split_  next to the token '
        'to block this sync.\nUse *<@{uid}> unsyncprofile* to cancel '
        'the process.').format(bot_cmd=bot_cmd, uid=slack_bot.my_uid,
                               bot_id=slack_bot.bot.user_self()['chat_id'])]

    text = '{} syncprofile {}'.format(bot_cmd, token)
    messages.append(text)
    messages.append(text + ' split')

    conv_1on1 = await slack_bot.get_slack1on1(user_id)
    for message in messages:
        slack_bot.send_message(channel=conv_1on1, text=message)


async def unsyncprofile(slack_bot, msg, dummys):
    """detach the slack profile from a previously attached G+ profile

    Args:
        slack_bot (core.SlackRTM): a running instance
        msg (message.SlackMessage): the currently handled instance
        dummys (tuple[str]): ignored

    Returns:
        tuple[str]: the channel target and the command output
    """
    user_id = msg.user.usr_id
    private_chat = await slack_bot.get_slack1on1(user_id)
    path = ['profilesync', slack_bot.identifier]
    bot = slack_bot.bot

    if bot.memory.exists(path + ['2ho', user_id]):
        chat_id = bot.memory.pop_by_path(path + ['2ho', user_id])
        bot.memory.pop_by_path(path + ['ho2', chat_id])

        # cleanup the 1on1 sync, if one was set
        for private_sync in slack_bot.get_syncs(channelid=private_chat):
            conv_1on1 = private_sync['hangoutid']
            slack_bot.config_disconnect(private_chat, conv_1on1)
        bot.memory.save()
        text = _('Slack and G+Profile are no more linked.')

    elif bot.memory.exists(path + ['pending_2ho', user_id]):
        token = bot.memory.pop_by_path(path + ['pending_2ho', user_id])
        bot.memory.pop_by_path(path + ['pending_ho2', token])
        bot.memory.pop_by_path(['profilesync', '_pending_', token])
        bot.memory.save()
        text = _('Profilesync canceled.')

    else:
        text = _('There is no G+Profile connected to your Slack Profile'
                 '.\nUse *<@{name}> syncprofile* to connect one'
                 ).format(name=slack_bot.my_uid)

    return private_chat, text


async def hangouts(slack_bot, msg, dummys):
    """admin-only: lists all hangouts

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        dummys (tuple[str]): ignored

    Returns:
        tuple[str]: the channel target and the command output
    """
    lines = []
    lines.append('@%s: list of active hangouts:\n' % msg.user.username)
    bot = slack_bot.bot
    for conv_id in bot.conversations:
        lines.append('*%s:* _%s_' % (
            bot.conversations.get_name(conv_id, conv_id), conv_id))
    return '1on1', '\n'.join(lines)


def listsyncs(slack_bot, msg, dummys):
    """admin-only: lists all running sync connections

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        dummys (tuple[str]): ignored

    Returns:
        tuple[str]: the channel target and the command output
    """
    lines = []
    lines.append('@%s: current syncs with this slack team:' % msg.user.username)
    for sync in slack_bot.syncs:
        conv_id = sync['hangoutid']
        hangout_name = slack_bot.bot.conversations.get_name(conv_id, conv_id)
        lines.append('*%s (%s) : %s (%s)*' % (
            slack_bot.get_chatname(sync['channelid'], 'unknown'),
            sync['channelid'], hangout_name, conv_id))
    return '1on1', '\n'.join(lines)


def _get_hangout_name(bot, conv_id):
    """get the name of a conversation and a error message with the convs id

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        conv_id (str): a possible hangouts conversation identifier

    Returns:
        tuple[str]: the found name or None and a error message
    """
    name = bot.conversations.get_name(conv_id, None)
    return name, _('sorry, but I\'m not a member of a Hangout with Id %s'
                   ) % conv_id


def syncto(slack_bot, msg, args):
    """admin-only: sync messages from current channel/group to specified hangout

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        args (tuple[str]): additional arguments as strings

    Returns:
        str: command output
    """
    message = '@%s: ' % msg.user.username
    if not args:
        message += _('sorry, but you have to specify a Hangout ID for `syncto`')
        return message

    hangoutid = args[0]

    hangout_name, text = _get_hangout_name(slack_bot.bot, hangoutid)

    if hangout_name is None:
        message += text
        return message

    try:
        slack_bot.config_syncto(msg.channel, hangoutid)
    except AlreadySyncingError:
        message += _('This channel is already synced with Hangout _%s_.') % (
            hangout_name)
    else:
        message += _('OK, I will now sync all messages in this channel with '
                     'Hangout _%s_.') % hangout_name

    return message


def disconnect(slack_bot, msg, args):
    """admin-only: stop syncing messages from current channel to a specified ho

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        args (tuple[str]): additional arguments as strings

    Returns:
        str: command output
    """
    message = '@%s: ' % msg.user.username
    if not args:
        message += _('sorry, but you have to specify a Hangout Id for '
                     '`disconnect`')
        return message

    hangoutid = args[0]
    hangout_name, text = _get_hangout_name(slack_bot.bot, hangoutid)

    if hangout_name is None:
        message += text
        return message

    try:
        slack_bot.config_disconnect(msg.channel, hangoutid)
    except NotSyncingError:
        message += _('This channel is *not* synced with the Hangout _%s_.') % (
            hangoutid)
    else:
        message += _('OK, I will no longer sync messages in this channel with '
                     'the Hangout _%s_.') % hangout_name
    return message


def chattitle(slack_bot, msg, args):
    """update the synced chattitle for the current or specified channel

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        args (tuple[str]): additional arguments as strings

    Returns:
        str: command output
    """
    return slack_bot.bot.call_shared(
        'setchattitle', args=args, platform=slack_bot.identifier,
        fallback=msg.channel, source=slack_bot.conversations)


def sync_config(slack_bot, msg, args):
    """update a config entry for the current or given channel

    Args:
        slack_bot (core.SlackRTM): the instance which received the message
        msg (message.SlackMessage): the currently handled message
        args (tuple[str]): additional arguments as strings

    Returns:
        str: command output
    """
    if len(args) < 2:
        return _("specify the config key and it's new value")

    if args[0] in slack_bot.conversations and len(args) > 2:
        channel = args[0]
        key = args[1]
        value = ' '.join(args[2:])
    else:
        channel = msg.channel
        key = args[0]
        value = ' '.join(args[1:])

    channel_tag = slack_bot.identifier + ':' + channel

    try:
        last_value, new_value = slack_bot.bot.call_shared(
            'sync_config', channel_tag, key, value)
    except (KeyError, TypeError) as err:
        return str(err)
    else:
        return _(
            '{sync_option} updated for channel "{channel_id}" from "{old}" to '
            '"{new}"'
        ).format(sync_option=key, channel_id=channel, old=last_value,
                 new=new_value)
