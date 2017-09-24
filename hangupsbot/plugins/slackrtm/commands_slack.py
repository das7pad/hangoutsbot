import asyncio
import logging
import sys

from .exceptions import (
    AlreadySyncingError,
    NotSyncingError,
    IgnoreMessage,
)
from .user import SlackUser


logger = logging.getLogger(__name__)


async def slack_command_handler(slackbot, msg):
    """parse themessage text and run the command of a message

    Args:
        slackbot (core.SlackRTM): a running instance
        msg (message.SlackMessage): the currently handled instance

    Raises:
        IgnoreMessage: do not sync the message as it is a slack-only command
    """
    if not msg.user_id:
        # do not respond to messages that originate from outside slack
        return

    tokens = msg.text.strip().split()

    if len(tokens) < 2:
        return

    if tokens.pop(0).lower() not in slackbot.command_prefixes:
        # not a command
        return

    command = tokens.pop(0).lower()
    args = tokens

    if command not in COMMANDS_USER and command not in COMMANDS_ADMIN:
        response = '@{}: {} is not recognised'.format(msg.username, command)

    elif command in COMMANDS_ADMIN and msg.user_id not in slackbot.admins:
        response = '@{}: {} is an admin-only command'.format(msg.username,
                                                             command)

    else:
        func = getattr(sys.modules[__name__], command)
        response = func(slackbot, msg, args)
        if asyncio.iscoroutinefunction(func):
            response = await response

    if isinstance(response, str):
        text = response
        channel = msg.channel

    elif isinstance(response, tuple):
        channel, text = response
        if channel == '1on1':
            channel = await slackbot.get_slack1on1(msg.user_id)

    else:
        # response from command that should not be send
        raise IgnoreMessage()

    slackbot.send_message(channel=channel, text=text, as_user=True,
                          link_names=True)
    raise IgnoreMessage()

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
}


# command definitions

def help(slackbot, msg, args):                # pylint:disable=redefined-builtin
    """list help for all available commands or query a single commands help"""
    if args and (args[0] in COMMANDS_USER or args[0] in COMMANDS_ADMIN):
        command = args[0].lower()
        return '1on1', '*%s*: %s' % (command, HELP[command])

    lines = ['*user commands:*']

    for command in COMMANDS_USER:
        lines.append('- *{}*: {}'.format(command, HELP[command]))

    if msg.user_id in slackbot.admins:
        lines.append('*admin commands:*')
        for command in COMMANDS_ADMIN:
            lines.append('- *{}*: {}'.format(command, HELP[command]))

    return '1on1', '\n\n'.join(lines)

def whereami(dummy, msg, dummys):
    """tells you the current channel/group id"""
    return _('@%s: you are in channel %s') % (msg.username, msg.channel)

def whoami(dummy, msg, dummys):
    """tells you your own user id"""
    return '1on1', _('@%s: your userid is %s') % (msg.username, msg.user_id)

def whois(slackbot, msg, args):
    """whois @username tells you the user id of @username"""
    if not args:
        return '1on1', _('%s: sorry, but you have to specify a username for '
                         'command `whois`') % (msg.username)

    search = args[0][1:] if args[0][0] == '@' else args[0]
    for uid in slackbot.users:
        if slackbot.get_username(uid) == search:
            message = _('@%s: the user id of _%s_ is %s') % (
                msg.username, slackbot.get_username(uid), uid)
            break
    else:
        message = _('%s: sorry, but I could not find user _%s_ in this slack.'
                   ) % (msg.username, search)
    return '1on1', message

def admins(slackbot, msg, dummys):
    """lists the slack users with admin privileges"""
    message = ['<@%s>: my admins are:' % msg.user_id]
    for admin in slackbot.admins:
        user = SlackUser(slackbot, channel=msg.channel, user_id=admin)
        message.append('<@%s> - %s' % (admin, user.full_name))

    return '1on1', '\n'.join(message)

async def syncprofile(slackbot, msg, dummys):
    """start the process to sync your slack profile with a G+profile

    Args:
        slackbot (core.SlackRTM): a running instance
        msg (message.SlackMessage): the currently handled instance
        dummys (tuple): additional arguments as strings

    Returns:
        tuple: a tuple of two strings, the channel target and the command output
    """
    bot = slackbot.bot
    user_id = msg.user_id
    path = ['profilesync', slackbot.identifier]

    if bot.memory.exists(path + ['2ho', user_id]):
        text = _('Your profile is already linked to a G+Profile, use '
                 '*<@{name}> unsyncprofile* to unlink your profiles'
                ).format(name=slackbot.my_uid)
        return '1on1', text

    if bot.memory.exists(path + ['pending_2ho', user_id]):
        text = _('* [ REMINDER ] *\n')
        token = bot.memory.get_by_path(
            path + ['pending_2ho', user_id])

    else:
        text = ''
        token = bot.sync.start_profile_sync(slackbot.identifier, user_id)

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
        'the process.').format(bot_cmd=bot_cmd, uid=slackbot.my_uid,
                               bot_id=slackbot.bot.user_self()['chat_id'])]

    text = '{} syncprofile {}'.format(bot_cmd, token)
    messages.append(text)
    messages.append(text + ' split')

    conv_1on1 = await slackbot.get_slack1on1(user_id)
    for message in messages:
        slackbot.send_message(channel=conv_1on1,
                              text=message, as_user=True, link_names=True)

async def unsyncprofile(slackbot, msg, dummys):
    """detach the slack profile from a previously attached G+ profile

    Args:
        slackbot (core.SlackRTM): a running instance
        msg (message.SlackMessage): the currently handled instance
        dummys (tuple): additional arguments as strings

    Returns:
        tuple: a tuple of two strings, the channel target and the command output
    """
    user_id = msg.user_id
    private_chat = await slackbot.get_slack1on1(user_id)
    path = ['profilesync', slackbot.identifier]
    bot = slackbot.bot

    if bot.memory.exists(path + ['2ho', user_id]):
        chat_id = bot.memory.pop_by_path(path + ['2ho', user_id])
        bot.memory.pop_by_path(path + ['ho2', chat_id])

        # cleanup the 1on1 sync, if one was set
        for private_sync in slackbot.get_syncs(channelid=private_chat):
            conv_1on1 = private_sync['hangoutid']
            slackbot.config_disconnect(private_chat, conv_1on1)
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
                ).format(name=slackbot.my_uid)

    return private_chat, text

async def hangouts(slackbot, msg, dummys):
    """admin-only: lists all connected hangouts, suggested: use only in direct message"""
    lines = []
    lines.append('@%s: list of active hangouts:\n' % msg.username)
    bot = slackbot.bot
    for conv_id in bot.conversations:
        lines.append('*%s:* _%s_' % (
            bot.conversations.get_name(conv_id, conv_id), conv_id))
    return '1on1', '\n'.join(lines)

def listsyncs(slackbot, msg, dummys):
    """admin-only: lists all runnging sync connections, suggested: use only in direct message"""
    lines = []
    lines.append('@%s: current syncs with this slack team:' % msg.username)
    for sync in slackbot.syncs:
        conv_id = sync['hangoutid']
        hangoutname = slackbot.bot.conversations.get_name(conv_id, conv_id)
        lines.append('*%s (%s) : %s (%s)*' % (
            slackbot.get_chatname(sync['channelid'], 'unknown'),
            sync['channelid'], hangoutname, conv_id))
    return '1on1', '\n'.join(lines)

def _get_hangout_name(bot, conv_id):
    """get the name of a conversation and a error message with the convs id

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        conv_id (str): a possible hangouts conversation identifier

    Returns:
        tuple: a tuple of two str: the found name or None and a error message
    """
    name = bot.conversations.get_name(conv_id, None)
    return name, _('sorry, but I\'m not a member of a Hangout with Id %s'
                  ) % (conv_id)

def syncto(slackbot, msg, args):
    """admin-only: sync messages from current channel/group to specified hangout, suggested: use only in direct message

    usage: syncto [hangout conversation id]"""
    message = '@%s: ' % msg.username
    if not args:
        message += _('sorry, but you have to specify a Hangout ID for `syncto`')
        return message

    hangoutid = args[0]

    hangoutname, text = _get_hangout_name(slackbot.bot, hangoutid)

    if hangoutname is None:
        message += text
        return message

    try:
        slackbot.config_syncto(msg.channel, hangoutid)
    except AlreadySyncingError:
        message += _('This channel is already synced with Hangout _%s_.') % (
            hangoutname)
    else:
        message += _('OK, I will now sync all messages in this channel with '
                     'Hangout _%s_.') % hangoutname
    return message

def disconnect(slackbot, msg, args):
    """admin-only: stop syncing messages from current channel/group to specified hangout, suggested: use only in direct message

    usage: disconnect [hangout conversation id]"""
    message = '@%s: ' % msg.username
    if not args:
        message += _('sorry, but you have to specify a Hangout Id for '
                     '`disconnect`')
        return message

    hangoutid = args[0]
    hangoutname, text = _get_hangout_name(slackbot.bot, hangoutid)

    if hangoutname is None:
        message += text
        return message

    try:
        slackbot.config_disconnect(msg.channel, hangoutid)
    except NotSyncingError:
        message += _('This channel is *not* synced with the Hangout _%s_.') % (
            hangoutid)
    else:
        message += _('OK, I will no longer sync messages in this channel with '
                     'the Hangout _%s_.') % hangoutname
    return message
