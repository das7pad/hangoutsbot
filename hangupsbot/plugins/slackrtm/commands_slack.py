import asyncio
import logging
import re
import sys

from .exceptions import (
    AlreadySyncingError,
    NotSyncingError,
    IgnoreMessage,
)


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

    await slackbot.send_message(channel=channel, text=text, as_user=True,
                                link_names=True)
    raise IgnoreMessage()

# command definitions

COMMANDS_USER = [
    "help",
    "whereami",
    "whoami",
    "whois",
    "admins",
    "syncprofile",
    "unsyncprofile",
]

COMMANDS_ADMIN = [
    "hangouts",
    "listsyncs",
    "syncto",
    "disconnect",
]

async def help(slackbot, msg, args):
    """list help for all available commands"""
    lines = ["*user commands:*\n"]

    for command in COMMANDS_USER:
        lines.append("* *{}*: {}\n".format(
            command,
            getattr(sys.modules[__name__], command).__doc__))

    if msg.user_id in slackbot.admins:
        lines.append("*admin commands:*\n")
        for command in COMMANDS_ADMIN:
            lines.append("* *{}*: {}\n".format(
                command,
                getattr(sys.modules[__name__], command).__doc__))

    await slackbot.send_message(
        channel=await slackbot.get_slack1on1(msg.user_id),
        text="\n".join(lines),
        as_user=True,
        link_names=True)

async def whereami(slackbot, msg, args):
    """tells you the current channel/group id"""

    await slackbot.send_message(
        channel=msg.channel,
        text=u'@%s: you are in channel %s' % (msg.username, msg.channel),
        as_user=True,
        link_names=True)

async def whoami(slackbot, msg, args):
    """tells you your own user id"""

    user_1on1 = await slackbot.get_slack1on1(msg.user_id)
    await slackbot.send_message(
        channel=user_1on1,
        text=u'@%s: your userid is %s' % (msg.username, msg.user_id),
        as_user=True,
        link_names=True)

async def whois(slackbot, msg, args):
    """whois @username tells you the user id of @username"""

    if not args:
        message = u'%s: sorry, but you have to specify a username for command `whois`' % (msg.username)
    else:
        user = args[0]
        userfmt = re.compile(r'^<@(.*)>$')
        match = userfmt.match(user)
        if match:
            user = match.group(1)
        if not user.startswith('U'):
            # username was given as string instead of mention, lookup in db
            for uid in slackbot.users:
                if slackbot.users[uid]['name'] == user:
                    user = uid
                    break
        if not user.startswith('U'):
            message = u'%s: sorry, but I could not find user _%s_ in this slack.' % (msg.username, user)
        else:
            message = u'@%s: the user id of _%s_ is %s' % (msg.username, slackbot.get_username(user), user)

    user_1on1 = await slackbot.get_slack1on1(msg.user_id)
    await slackbot.send_message(
        channel=user_1on1,
        text=message,
        as_user=True,
        link_names=True)

async def admins(slackbot, msg, args):
    """lists the slack users with admin privileges"""

    message = '@%s: my admins are:\n' % msg.username
    for admin in slackbot.admins:
        message += '@%s: _%s_\n' % (slackbot.get_username(admin), admin)
    user_1on1 = await slackbot.get_slack1on1(msg.user_id)
    await slackbot.send_message(
        channel=user_1on1,
        text=message,
        as_user=True,
        link_names=True)

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
        await slackbot.send_message(channel=conv_1on1,
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

async def hangouts(slackbot, msg, args):
    """admin-only: lists all connected hangouts, suggested: use only in direct message"""

    message = '@%s: list of active hangouts:\n' % msg.username
    bot = slackbot.bot
    for conv_id in bot.conversations:
        message += '*%s:* _%s_\n' % (bot.conversations.get_name(conv_id),
                                     conv_id)
    user_1on1 = await slackbot.get_slack1on1(msg.user_id)
    await slackbot.send_message(
        channel=user_1on1,
        text=message,
        as_user=True,
        link_names=True)

async def listsyncs(slackbot, msg, args):
    """admin-only: lists all runnging sync connections, suggested: use only in direct message"""

    message = '@%s: list of current sync connections with this slack team:\n' % msg.username
    for sync in slackbot.syncs:
        hangoutname = slackbot.bot.conversations.get_name(sync['hangoutid'],
                                                          'unknown')
        message += '*%s (%s) : %s (%s)*\n' % (
            slackbot.get_chatname(sync['channelid'], 'unknown'),
            sync['channelid'],
            hangoutname,
            sync['hangoutid'],
            )
    user_1on1 = await slackbot.get_slack1on1(msg.user_id)
    await slackbot.send_message(
        channel=user_1on1,
        text=message,
        as_user=True,
        link_names=True)

async def syncto(slackbot, msg, args):
    """admin-only: sync messages from current channel/group to specified hangout, suggested: use only in direct message

    usage: syncto [hangout conversation id]"""

    message = '@%s: ' % msg.username
    if not args:
        message += u'sorry, but you have to specify a Hangout Id for command `syncto`'
        await slackbot.send_message(channel=msg.channel, text=message, as_user=True, link_names=True)
        return

    hangoutid = args[0]
    hangoutname = slackbot.bot.conversations.get_name(hangoutid, None)
    if hangoutname is None:
        message += u'sorry, but I\'m not a member of a Hangout with Id %s' % hangoutid
        await slackbot.send_message(
            channel=msg.channel,
            text=message,
            as_user=True,
            link_names=True)
        return

    if msg.channel.startswith('D'):
        channelname = 'DM'
    else:
        channelname = '#%s' % slackbot.get_chatname(msg.channel)

    try:
        slackbot.config_syncto(msg.channel, hangoutid)
    except AlreadySyncingError:
        message += u'This channel (%s) is already synced with Hangout _%s_.' % (channelname, hangoutname)
    else:
        message += u'OK, I will now sync all messages in this channel (%s) with Hangout _%s_.' % (channelname, hangoutname)
    await slackbot.send_message(
        channel=msg.channel,
        text=message,
        as_user=True,
        link_names=True)

async def disconnect(slackbot, msg, args):
    """admin-only: stop syncing messages from current channel/group to specified hangout, suggested: use only in direct message

    usage: disconnect [hangout conversation id]"""

    message = '@%s: ' % msg.username
    if not args:
        message += u'sorry, but you have to specify a Hangout Id for command `disconnect`'
        await slackbot.send_message(channel=msg.channel, text=message, as_user=True, link_names=True)
        return

    hangoutid = args[0]
    hangoutname = slackbot.bot.conversations.get_name(hangoutid, None)
    if hangoutname is None:
        message += u'sorry, but I\'m not a member of a Hangout with Id %s' % hangoutid
        await slackbot.send_message(channel=msg.channel, text=message, as_user=True, link_names=True)
        return

    if msg.channel.startswith('D'):
        channelname = 'DM'
    else:
        channelname = '#%s' % slackbot.get_chatname(msg.channel)
    try:
        slackbot.config_disconnect(msg.channel, hangoutid)
    except NotSyncingError:
        message += u'This channel (%s) is *not* synced with Hangout _%s_.' % (channelname, hangoutid)
    else:
        message += u'OK, I will no longer sync messages in this channel (%s) with Hangout _%s_.' % (channelname, hangoutname)
    await slackbot.send_message(
        channel=msg.channel,
        text=message,
        as_user=True,
        link_names=True)
