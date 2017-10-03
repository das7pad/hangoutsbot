# TODO(das7pad) refactor needed

import logging
import shlex

import hangups

import plugins

from commands import Help


logger = logging.getLogger(__name__)


def _initialise(bot):
    plugins.register_admin_command(["convecho", "convfilter", "convleave", "convrename", "convusers"])


def get_posix_args(rawargs):
    lexer = shlex.shlex(" ".join(rawargs), posix=True)
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
        for convid, convdata in bot.conversations.get(filter=posix_args[0]).items():
            lines.append("`{}` <b>{}</b> ({})".format(convid, convdata["title"], len(convdata["participants"])))
        lines.append(_('<b>Total: {}</b>').format(len(lines)))
        message = '\n'.join(lines)

        await bot.coro_send_message(event.conv_id, message)

        return {"api.response" : message}


async def convecho(bot, event, *args):
    """echo back text into filtered conversations"""
    posix_args = get_posix_args(args)

    if (len(posix_args) > 1):
        if not posix_args[0]:
            """block spamming ALL conversations"""
            return _("<em>sending to ALL conversations not allowed</em>")
        convlist = bot.conversations.get(filter=posix_args[0])
        text = ' '.join(posix_args[1:])
    elif len(posix_args) == 1 and posix_args[0].startswith("id:"):
        """specialised error message for /bot echo (implied convid: <event.conv_id>)"""
        raise Help(_("<em>missing text</em>"))
    else:
        """general error"""
        raise Help(_("<em>required parameters: convfilter text</em>"))

    if not convlist:
        return _("<em>no conversations filtered</em>")

    for convid in convlist:
        await bot.coro_send_message(convid, text)


async def convrename(bot, event, *args):
    """renames a single specified conversation"""
    posix_args = get_posix_args(args)

    if len(posix_args) > 1:
        if not posix_args[0].startswith(("id:", "text:")):
            # always force explicit search for single conversation on vague user request
            posix_args[0] = "id:" + posix_args[0]
        convlist = bot.conversations.get(filter=posix_args[0])
        title = ' '.join(posix_args[1:])

        # only act on the first matching conversation

        await bot._client.rename_conversation(
            hangups.hangouts_pb2.RenameConversationRequest(
                request_header=bot._client.get_request_header(),
                new_name=title,
                event_request_header=hangups.hangouts_pb2.EventRequestHeader(
                    conversation_id=hangups.hangouts_pb2.ConversationId(
                        id=list(convlist.keys())[0]),
                    client_generated_id=bot._client.get_client_generated_id())))

    elif len(posix_args) == 1 and posix_args[0].startswith("id:"):
        """specialised error message for /bot rename (implied convid: <event.conv_id>)"""
        raise Help(_("<em>missing title</em>"))
    else:
        """general error"""
        raise Help(_("<em>required parameters: convfilter title</em>"))


async def convusers(bot, event, *args):
    """gets list of users for specified conversation filter"""
    posix_args = get_posix_args(args)

    if len(posix_args) != 1:
        raise Help(_("<em>should be 1 parameter, {} supplied</em>").format(
            len(posix_args)))
    if not posix_args[0]:
        """don't do it in all conversations - might crash hangups"""
        return _("<em>retrieving ALL conversations blocked</em>")

    chunks = [] # one "chunk" = info for 1 hangout
    for convdata in bot.conversations.get(filter=posix_args[0]).values():
        lines = []
        lines.append(_('Users in <b>{}</b>').format(
            convdata["title"], len(convdata["participants"])))
        for chat_id in convdata["participants"]:
            User = bot.get_hangups_user(chat_id)
            # name and G+ link
            _line = '<b><a href="https://plus.google.com/{}">{}</a></b>'.format(
                User.id_.chat_id, User.full_name)
            # email from hangups UserList (if available)
            if User.emails:
                _line += '\n... (<a href="mailto:{0}">{0}</a>)'.format(
                    User.emails[0])
            # user id
            _line += "\n... {}".format(User.id_.chat_id) # user id
            lines.append(_line)
        lines.append(_('<b>Users: {}</b>').format(
            len(convdata["participants"])))
        chunks.append('\n'.join(lines))
    message = '\n\n'.join(chunks)

    await bot.coro_send_message(event.conv_id, message)

    return {"api.response" : message}


async def convleave(bot, event, *args):
    """leave specified conversation(s)"""
    posix_args = get_posix_args(args)

    if (len(posix_args) >= 1):
        if not posix_args[0]:
            """block leaving ALL conversations"""
            return _("<em>cannot leave ALL conversations</em>")
        convlist = bot.conversations.get(filter=posix_args[0])
    else:
        """general error"""
        raise Help(_("<em>required parameters: convfilter</em>"))

    for convid, convdata in convlist.items():
        if convdata["type"] == "GROUP":
            if not "quietly" in posix_args:
                await bot.coro_send_message(convid, _('I\'ll be back!'))

            try:
                await bot._client.remove_user(
                    hangups.hangouts_pb2.RemoveUserRequest(
                        request_header=bot._client.get_request_header(),
                        event_request_header=hangups.hangouts_pb2.EventRequestHeader(
                            conversation_id=hangups.hangouts_pb2.ConversationId(
                                id=convid),
                            client_generated_id=bot._client.get_client_generated_id())))

                if convid in bot._conv_list._conv_dict:
                    # replicate hangups behaviour - remove conversation from internal dict
                    del bot._conv_list._conv_dict[convid]
                bot.conversations.remove(convid)

            except hangups.NetworkError as e:
                logging.exception("CONVLEAVE: error leaving {} {}".format(convid, convdata["title"]))

        else:
            logging.warning("CONVLEAVE: cannot leave {} {} {}".format(convdata["type"], convid, convdata["title"]))
