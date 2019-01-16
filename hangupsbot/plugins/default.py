"""basic commands for the HangupsBot"""
import json
import logging
import re

import hangups

from hangupsbot import plugins
from hangupsbot.commands import (
    Help,
    command,
)
from hangupsbot.utils import remove_accents


logger = logging.getLogger(__name__)

HELP = {
    "echo": _("echo back a given text into a conversation\nto echo into an "
              "other conversation provide a conv_id a the first argument"),

    "broadcast": _("broadcast a message to conversations\n{bot_cmd} broadcast "
                   "[info|message|add|remove|NOW]"),

    "users": _("list all users in the current hangout with their G+IDs"),

    "hangouts": _("list all hangouts, supply keywords to filter by title"),

    "rename": _("rename current hangout"),

    "leave": _("exits current or other specified hangout"),

    "reload": _("reload config and memory, useful if manually edited on running"
                " bot"),

    "quit": _("stop running"),

    "config": _("displays or modifies the configuration\n"
                "* {bot_cmd} config get [key] [subkey] [...]\n"
                "* {bot_cmd} config set [key] [subkey] [...] [value]\n"
                "* {bot_cmd} config append [key] [subkey] [...] [value]\n"
                "* {bot_cmd} config remove [key] [subkey] [...] [value]\n\n"
                "note: override and display within group conversation with "
                "{bot_cmd} config here [command]"),

    "whoami": _("get your user id"),

    "whereami": _("get current conversation id"),
}

# non-persistent internal state independent of config.json/memory.json
_INTERNAL = {"broadcast": {"message": "", "conversations": []}}  # /bot broadcast


def _initialise():
    """register the commands and their help entries"""
    plugins.register_admin_command([
        "broadcast",
        "users",
        "user",
        "hangouts",
        "rename",
        "leave",
        "reload",
        "quit",
        "config",
        "whereami",
    ])
    plugins.register_user_command([
        "echo",
        "whoami",
    ])
    plugins.register_help(HELP)


def echo(bot, event, *args):
    """echo a message back to the current or given conversation

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): message wrapper
        args (str): request body

    Returns:
        tuple[str]: the conversation target and the message

    Raises:
        Help: invalid request
    """
    if not args:
        raise Help(_('supply a message!'))

    if len(args) > 1 and args[0] in bot.conversations:
        # /bot echo <convid> <text>
        # only admins can echo messages into other conversations
        admins_list = bot.get_config_suboption(args[0], 'admins')
        if event.user_id.chat_id in admins_list:
            convid = args[0]
            text = tuple(args[1:])
        else:
            convid = event.conv_id
            text = (_("<b>only admins can echo other conversations</b>"),)

    else:
        # /bot echo <text>
        convid = event.conv_id
        text = args

    return convid, " ".join(text)


async def broadcast(bot, dummy, *args):
    """broadcast a message to multiple chats, schedule here

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        dummy: event.ConversationEvent instance, not needed
        args (str): request body

    Returns:
        str: user output

    Raises:
        Help: bad request
    """
    if not args:
        raise Help(_('Your request is missing'))
    sub_cmd = args[0]
    parameters = args[1:]
    if sub_cmd == "info":
        # display broadcast data such as message and target rooms

        conv_info = [
            "<b><i>{name}</i></b> ... <i>{conv_id}</i>".format(
                name=bot.conversations.get_name(convid, '~'),
                conv_id=convid)
            for convid in _INTERNAL["broadcast"]["conversations"]
        ]

        if not _INTERNAL["broadcast"]["message"]:
            text = [_("broadcast: no message set")]

        elif not conv_info:
            text = [_("broadcast: no conversations available")]

        else:
            text = [_("<b>message:</b>"), _INTERNAL["broadcast"]["message"],
                    _("<b>to:</b>")]
            text.extend(conv_info)

    elif sub_cmd == "message":
        # set broadcast message
        message = ' '.join(parameters)
        if message:
            _INTERNAL["broadcast"]["message"] = message
            text = [_("{} saved").format(message)]

        else:
            text = [_("broadcast: message must be supplied after sub command")]

    elif sub_cmd == "add":
        # add conversations to a broadcast
        if parameters[0] == "groups":
            # add all groups
            _INTERNAL["broadcast"]["conversations"].extend(
                list(bot.conversations.get("type:group")))

        elif parameters[0] == "ALL":
            # add EVERYTHING - try not to use this, will message 1-to-1s as well
            _INTERNAL["broadcast"]["conversations"].extend(
                list(bot.conversations.get()))

        else:
            # add by wild card search of title or id
            search = " ".join(parameters)
            for convid, convdata in bot.conversations.get().items():
                if (search.lower() in convdata["title"].lower() or
                        search in convid):
                    _INTERNAL["broadcast"]["conversations"].append(convid)

        _INTERNAL["broadcast"]["conversations"] = list(
            set(_INTERNAL["broadcast"]["conversations"]))
        text = [_("broadcast: {conv_count} conversation(s)").format(
            conv_count=len(_INTERNAL["broadcast"]["conversations"]))]

    elif sub_cmd == "remove":
        if parameters[0].lower() == "all":
            # remove all conversations from broadcast
            _INTERNAL["broadcast"]["conversations"] = []
            text = [_("broadcast: cleared all conversations")]

        else:
            # remove by wild card search of title or id
            search = " ".join(parameters)
            removed = []
            for convid in _INTERNAL["broadcast"]["conversations"]:
                if (search.lower() in bot.conversations.get_name(convid).lower()
                        or search in convid):
                    _INTERNAL["broadcast"]["conversations"].remove(convid)
                    removed.append(
                        _("<b><i>{name}</i></b> (<i>{conv_id}</i>)").format(
                            name=bot.conversations.get_name(convid),
                            conv_id=convid))

            text = [_("broadcast: removed {conv_tags}".format(
                conv_tags=", ".join(removed)))]

    elif sub_cmd == "NOW":
        # send the broadcast
        context = {"syncroom_no_repeat": True}  # prevent echos across syncrooms
        for convid in _INTERNAL["broadcast"]["conversations"]:
            await bot.coro_send_message(convid,
                                        _INTERNAL["broadcast"]["message"],
                                        context=context)
        text = [_("broadcast: message sent to {conv_count} chats").format(
            conv_count=len(_INTERNAL["broadcast"]["conversations"]))]

    else:
        raise Help()

    return "\n".join(text)


async def users(bot, event, *dummys):
    """forward the call to the commands equivalent"""
    await command.run(bot, event, *["convusers", "id:" + event.conv_id])


def user(bot, dummy, *args):
    """find people by name

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        dummy (hangupsbot.event.ConversationEvent): not used
        args (str): additional words passed to the command

    Returns:
        list[hangups.ChatMessageSegment]: formatted command output

    Raises:
        Help: invalid request
    """

    search = " ".join(args)

    if not search:
        raise Help(_("supply search term"))

    search_lower = search.strip().lower()
    search_upper = search.strip().upper()

    line_break = hangups.ChatMessageSegment(
        text='\n', segment_type=hangups.hangouts_pb2.SEGMENT_TYPE_LINE_BREAK)

    segments = [
        hangups.ChatMessageSegment(
            _('results for user named "{}":').format(search),
            is_bold=True),
    ]

    all_known_users = {}
    for chat_id in bot.memory["user_data"]:
        all_known_users[chat_id] = bot.get_hangups_user(chat_id)

    for usr in sorted(all_known_users.values(),
                      key=lambda x: x.full_name.split()[-1]):
        fullname_lower = usr.full_name.lower()
        fullname_upper = usr.full_name.upper()
        non_spaced_lower = re.sub(r'\s+', '', fullname_lower)
        non_spaced_upper = re.sub(r'\s+', '', usr.full_name.upper())

        if (search_lower in fullname_lower
                or search_lower in non_spaced_lower
                # XXX: turkish alphabet special case:
                #  conversation works better when uppercase
                or search_upper in remove_accents(fullname_upper)
                or search_upper in remove_accents(non_spaced_upper)):

            segments.append(line_break)

            link = 'https://plus.google.com/u/0/{}/about'.format(usr.id_.chat_id)
            segments.append(
                hangups.ChatMessageSegment(
                    text=usr.full_name,
                    segment_type=hangups.hangouts_pb2.SEGMENT_TYPE_LINK,
                    link_target=link))
            if usr.emails:
                segments.append(hangups.ChatMessageSegment(' ('))
                segments.append(
                    hangups.ChatMessageSegment(
                        text=usr.emails[0],
                        segment_type=hangups.hangouts_pb2.SEGMENT_TYPE_LINK,
                        link_target='mailto:{}'.format(usr.emails[0])))
                segments.append(hangups.ChatMessageSegment(')'))
            segments.append(
                hangups.ChatMessageSegment(' ... {}'.format(usr.id_.chat_id)))

    return segments


def hangouts(bot, dummy, *args):
    """retrieve a list of hangouts, supply a search term in args to filter

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        dummy (hangupsbot.event.ConversationEvent): not used
        args (str): the search term

    Returns:
        str: the command output
    """
    text_search = " ".join(args)

    if not (args and
            args[0].strip("(").startswith(("text:", "chat_id:", "type:",
                                           "minusers:", "maxusers:", "tag:"))):
        text_search = "text:" + text_search

    lines = []
    for convid, convdata in bot.conversations.get(text_search).items():
        lines.append("<b>{title}</b>: <i>{conv_id}</i>".format(
            title=convdata["title"], conv_id=convid))

    lines.append(_("<b>Total: {lines_num}</b>").format(lines_num=len(lines)))

    if text_search:
        lines.insert(0, _('<b>List of hangouts matching:</b> "<i>{term}</i>"'
                          ).format(term=text_search))

    return "\n".join(lines)


async def rename(bot, event, *args):
    """rename the current conversation

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): the new chat title
    """
    await command.run(bot, event, *["convrename", "id:" + event.conv_id,
                                    " ".join(args)])


async def leave(bot, event, *args):
    """leave the current or given conversation

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): a different conv_id, 'quietly' to skip an output
    """
    parameters = set(args)
    if "quietly" in args:
        parameters.discard("quietly")
        quietly = True
    else:
        quietly = False

    if len(parameters) == 1:
        conversation_id = parameters.pop()
    else:
        conversation_id = event.conv_id

    await command.run(bot, event, *["convleave", "id:" + conversation_id,
                                    "quietly" if quietly else ""])


async def reload(bot, event, *dummys):
    """reload .config and .memory from file

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        dummys (str): ignored
    """
    await bot.coro_send_message(event.conv, "<b>reloading config.json</b>")
    bot.config.load()

    await bot.coro_send_message(event.conv, "<b>reloading memory.json</b>")
    bot.memory.load()


def quit(bot, event, *dummys):  # pylint:disable=redefined-builtin
    """kill the bot

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        dummys (str): ignored
    """
    logger.warning('HangupsBot killed by user %s from conversation %s',
                   event.user.full_name, event.conv.name)
    bot.stop()


async def config(bot, event, *args):
    """retrieve or edit a config entry

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): additional words to for a request

    Returns:
        str: request result or None if the output was redirected to a pHO

    Raises:
        Help: invalid request
        KeyError: the given path does not exist
        ValueError: the given value is not a valid json
    """

    def _test():
        try:
            return json.loads(' '.join(tokens))
        except ValueError:
            return 'INVALID JSON'

    def _get():
        return (bot.config.get_by_path(config_path)
                if config_path else dict(bot.config))

    def _set():
        bot.config.set_by_path(config_path, json.loads(value))
        bot.config.save()
        return bot.config.get_by_path(config_path)

    def _append():
        current = bot.config.get_by_path(config_path)
        if not isinstance(current, list):
            return _('APPEND FAILED ON NON-LIST')

        current.append(json.loads(value))
        bot.config.set_by_path(config_path, current)
        bot.config.save()
        return current

    def _remove():
        current = bot.config.get_by_path(config_path)
        if not isinstance(current, list):
            return _('REMOVE FAILED ON NON-LIST')

        current.remove(json.loads(value))
        bot.config.set_by_path(config_path, current)
        bot.config.save()
        return current

    # TODO(das7pad): validate the new value/path

    # consume arguments and differentiate beginning of a json array or object
    cmd, *tokens = args or (None,)
    config_path = []
    value_items = []
    state = "key"

    # allow admin to override default output to 1-on-1
    chat_response_private = True
    if cmd == 'here':
        chat_response_private = False
        if tokens:
            cmd = tokens.pop(0)
        else:
            cmd = None

    for token in tokens:
        if token.startswith(("{", "[", '"', "'")):
            # apparent start of json object, consume into a single list item
            state = "json"
        if state == "key":
            config_path.append(token)
        elif state == "json":
            value_items.append(token)
        else:
            raise Help("unknown state")

    if cmd == 'get' or cmd is None:
        value = _get()

    elif cmd == 'test':
        value = _test()
        return json.dumps(value, indent=2, sort_keys=True)

    elif cmd in ('set', 'append', 'remove'):
        if not config_path:
            raise Help('MISSING PATH')

        if not value_items:
            raise Help('MISSING VALUE')

        value = " ".join(value_items)

        if cmd == 'set':
            value = _set()

        elif cmd == 'append':
            value = _append()

        elif cmd == 'remove':
            value = _remove()

    else:
        await command.unknown_command(bot, event)
        return

    if value is None:
        value = _('Parameter does not exist!')

    output = '<b>config {}:</b>\n'.format(' '.join(config_path))
    output += json.dumps(value, indent=2, sort_keys=True)

    if chat_response_private:
        await bot.coro_send_to_user(event.user_id.chat_id, output)
    else:
        return output


def whoami(bot, event, *dummys):
    """retrieve the users G+id

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        dummys (str): ignored

    Returns:
        str: a status message
    """
    path = ['user_data', event.user_id.chat_id, "label"]
    if bot.memory.exists(path):
        fullname = bot.memory.get_by_path(path)
    else:
        fullname = event.user.full_name

    return _("<b><i>{fullname}</i></b>, chat_id = <i>{chat_id}</i>").format(
        fullname=fullname, chat_id=event.user_id.chat_id)


def whereami(dummy, event, *dummys):
    """retrieve the current conversation identifier

    Args:
        dummy (hangupsbot.core.HangupsBot): the running instance, not used
        event (hangupsbot.event.ConversationEvent): a message container
        dummys (str): ignored

    Returns:
        str: a status message
    """
    return _("You are at <b><i>{conv_name}</i></b>, "
             "conv_id = <i>{conv_id}</i>").format(conv_name=event.conv.name,
                                                  conv_id=event.conv_id)
