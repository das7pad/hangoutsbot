"""schedule a reminder in a pubilc or private conversation"""
import asyncio

from hangupsbot import plugins
from hangupsbot.commands import Help


HELP = {
    'remindme': _("Posts a custom message to a 1on1 after a delay\nUsage: "
                  "{bot_cmd} remindme <b><delay (minutes)></b> <i>Message</i>"
                  "\nexample: {bot_cmd} remindme 5 The 5 Minutes are OVER"),

    'remindall': _("Posts a custom message to the chat after a delay\nUsage: "
                   "{bot_cmd} remindall <b><delay (minutes)></b> <i>Message</i>"
                   "\nexample: {bot_cmd} remindall 5 The 5 Minutes are OVER"),
}

def _initialise():
    """register the commands and their help entrys"""
    plugins.register_user_command(["remindme", "remindall"])
    plugins.register_help(HELP)

def _get_delay(args):
    """check if enough args are specified and whether a valid delay is given

    Args:
        args: tuple of string, argument passed to the command

    Returns:
        float, the specified delay

    Raises:
        commands.Help: not enough args specified or invalid delay given
    """
    if len(args) < 2:
        raise Help(_("specify delay and message"))

    try:
        return float(args[0])*60.0
    except ValueError:
        raise Help(_('invalid delay "%s" given, integer or float required')
                   % args[0])

async def remindme(bot, event, *args):
    """schedule a message for the private chat with the bot

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple of strings, delay and message content

    Returns:
        string, confirmation of the schedules message

    Raises:
        commands.Help: invalid request, either too few args or invalid delay
    """
    delay = _get_delay(args)
    full_name = event.user.full_name
    conv_1on1 = await bot.get_1to1(event.user.id_.chat_id, force=True)
    if not conv_1on1:
        return _("%s, chat with me in a private chat first") % full_name

    asyncio.ensure_future(_reminder(bot, conv_1on1, delay, args))

    return _("Private reminder for <b>{}</b> in {}m").format(full_name, args[0])

async def remindall(bot, event, *args):
    """schedule a message in the current conversation

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple of strings, delay and message content

    Returns:
        string, confirmation of the schedules message

    Raises:
        commands.Help: invalid request, either too few args or invalid delay
    """
    delay = _get_delay(args)

    asyncio.ensure_future(_reminder(bot, event.conv_id, delay, args))

    return _("Public reminder in {}m").format(args[0])

async def _reminder(bot, conv_id, delay, args):
    """detached execution of a remind/remindall request

    Args:
        bot: HangupsBot instance
        conv_id: string, Hangouts conversation identifier
        delay: float, time in seconds to sleep before sending the reminder
        args: tuple of strings, reminder text
    """
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    await bot.coro_send_message(conv_id,
                                _("<b>Reminder:</b> ") + " ".join(args[1:]))
