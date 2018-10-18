# TODO(das7pad) refactor needed

import logging
import shlex

import hangups

from hangupsbot import plugins
from hangupsbot.commands import Help


logger = logging.getLogger(__name__)


def _initialise():
    plugins.register_admin_command([
        "convecho",
        "convfilter",
        "convleave",
        "convrename",
        "convusers",
    ])


def get_posix_args(raw_args):
    lexer = shlex.shlex(" ".join(raw_args), posix=True)
    lexer.commenters = ""
    lexer.wordchars += "!@#$%^&*():/.<>?[]-,=+;|"
    posix_args = list(lexer)
    return posix_args


async def convfilter(bot, event, *args):
    """test filter and return matched conversations"""
    posix_args = get_posix_args(args)

    if len(posix_args) > 1:
        raise Help(_("<em>1 parameter required, {} supplied - enclose parameter"
                     " in double-quotes</em>").format(len(posix_args)))
    elif not posix_args:
        raise Help(_("<em>supply 1 parameter</em>"))
    else:
        lines = []
        for convid, convdata in bot.conversations.get(
                filter=posix_args[0]).items():
            lines.append(
                "`{}` <b>{}</b> ({})".format(
                    convid, convdata["title"], len(convdata["participants"]))
            )
        lines.append(_('<b>Total: {}</b>').format(len(lines)))
        message = '\n'.join(lines)

        await bot.coro_send_message(event.conv_id, message)

        return {"api.response": message}


async def convecho(bot, dummy, *args):
    """echo back text into filtered conversations"""
    posix_args = get_posix_args(args)

    if len(posix_args) > 1:
        if not posix_args[0]:
            # block spamming ALL conversations
            return _("<em>sending to ALL conversations not allowed</em>")
        convlist = bot.conversations.get(filter=posix_args[0])
        text = ' '.join(posix_args[1:])
    elif len(posix_args) == 1 and posix_args[0].startswith("id:"):
        # specialised error message for
        #  /bot echo (implied convid: <event.conv_id>)
        raise Help(_("<em>missing text</em>"))
    else:
        # general error
        raise Help(_("<em>required parameters: convfilter text</em>"))

    if not convlist:
        return _("<em>no conversations filtered</em>")

    for convid in convlist:
        await bot.coro_send_message(convid, text)


async def convrename(bot, dummy, *args):
    """renames a single specified conversation"""
    posix_args = get_posix_args(args)

    if len(posix_args) > 1:
        if not posix_args[0].startswith(("id:", "text:")):
            # always force explicit search for single conversation on
            #  vague user request
            posix_args[0] = "id:" + posix_args[0]
        convlist = bot.conversations.get(filter=posix_args[0])
        title = ' '.join(posix_args[1:])
        if not convlist:
            return _('No conversation matched "%s"') % posix_args[0]
        # only act on the first matching conversation
        conv_id = list(convlist)[0]
        conv = bot.get_conversation(conv_id)
        try:
            await conv.rename(title)
        except hangups.NetworkError:
            return _('Failed to rename!')

    elif len(posix_args) == 1 and posix_args[0].startswith("id:"):
        # specialised error message for
        #  /bot rename (implied convid: <event.conv_id>)
        raise Help(_("<em>missing title</em>"))
    else:
        # general error
        raise Help(_("<em>required parameters: convfilter title</em>"))


async def convusers(bot, event, *args):
    """gets list of users for specified conversation filter"""
    posix_args = get_posix_args(args)

    if len(posix_args) != 1:
        raise Help(_("<em>should be 1 parameter, {} supplied</em>").format(
            len(posix_args)))
    if not posix_args[0]:
        # don't do it in all conversations - might crash hangups
        return _("<em>retrieving ALL conversations blocked</em>")

    chunks = []  # one "chunk" = info for 1 hangout
    for convdata in bot.conversations.get(filter=posix_args[0]).values():
        lines = [
            _('Users in <b>{}</b>').format(
                convdata["title"], len(convdata["participants"])),
        ]
        for chat_id in convdata["participants"]:
            user = bot.get_hangups_user(chat_id)
            # name and G+ link
            _line = '<b><a href="https://plus.google.com/{}">{}</a></b>'.format(
                user.id_.chat_id, user.full_name)
            # email from hangups UserList (if available)
            if user.emails:
                _line += '\n... (<a href="mailto:{0}">{0}</a>)'.format(
                    user.emails[0])
            # user id
            _line += "\n... {}".format(user.id_.chat_id)
            lines.append(_line)
        lines.append(_('<b>Users: {}</b>').format(
            len(convdata["participants"])))
        chunks.append('\n'.join(lines))
    message = '\n\n'.join(chunks)

    await bot.coro_send_message(event.conv_id, message)

    return {"api.response": message}


async def convleave(bot, dummy, *args):
    """leave specified conversation(s)"""
    posix_args = get_posix_args(args)

    if len(posix_args) >= 1:
        if not posix_args[0]:
            # block leaving ALL conversations
            return _("<em>cannot leave ALL conversations</em>")
        convlist = bot.conversations.get(filter=posix_args[0])
    else:
        # general error
        raise Help(_("<em>required parameters: convfilter</em>"))

    for convid, convdata in convlist.items():
        if convdata["type"] == "GROUP":
            if "quietly" not in posix_args:
                await bot.coro_send_message(convid, _('I\'ll be back!'))

            try:
                # pylint:disable=protected-access
                await bot._conv_list.leave_conversation(convid)
                bot.conversations.remove(convid)

            except hangups.NetworkError:
                logging.exception("CONVLEAVE: error leaving %s %s",
                                  convid, convdata["title"])

        else:
            logging.warning("CONVLEAVE: cannot leave %s %s %s",
                            convdata["type"], convid, convdata["title"])
