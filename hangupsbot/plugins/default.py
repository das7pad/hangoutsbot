"""basic commands for the HangupsBot"""
import re
import json
import logging

import hangups

from hangupsbot import plugins
from hangupsbot.utils import remove_accents
from hangupsbot.commands import command, Help


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
_INTERNAL = {"broadcast": {"message": "", "conversations": []}} # /bot broadcast

def _initialise():
    """register the commands and their help entries"""
    plugins.register_admin_command(["broadcast", "users", "user", "hangouts",
                                    "rename", "leave", "reload", "quit",
                                    "config", "whereami"])
    plugins.register_user_command(["echo", "whoami"])
    plugins.register_help(HELP)


def echo(bot, event, *args):
    """echo a message back to the current or given conversation

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): message wrapper
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
        bot (hangupsbot.HangupsBot): the running instance
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

        conv_info = ["<b><i>{name}</i></b> ... <i>{conv_id}</i>".format(
            name=bot.conversations.get_name(convid, '~'), conv_id=convid)
                     for convid in _INTERNAL["broadcast"]["conversations"]]

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
        context = {"syncroom_no_repeat": True} # prevent echos across syncrooms
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
        bot (hangupsbot.HangupsBot): the running instance
        dummy (event.ConversationEvent): not used
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

    segments = [hangups.ChatMessageSegment(_('results for user named "{}":').format(search),
                                           is_bold=True),
                hangups.ChatMessageSegment('\n', hangups.hangouts_pb2.SEGMENT_TYPE_LINE_BREAK)]

    all_known_users = {}
    for chat_id in bot.memory["user_data"]:
        all_known_users[chat_id] = bot.get_hangups_user(chat_id)

    for usr in sorted(all_known_users.values(), key=lambda x: x.full_name.split()[-1]):
        fullname_lower = usr.full_name.lower()
        fullname_upper = usr.full_name.upper()
        non_spaced_lower = re.sub(r'\s+', '', fullname_lower)
        non_spaced_upper = re.sub(r'\s+', '', usr.full_name.upper())

        if (search_lower in fullname_lower
                or search_lower in non_spaced_lower
                # XXX: turkish alphabet special case: conversation works better when uppercase
                or search_upper in remove_accents(fullname_upper)
                or search_upper in remove_accents(non_spaced_upper)):

            link = 'https://plus.google.com/u/0/{}/about'.format(usr.id_.chat_id)
            segments.append(hangups.ChatMessageSegment(usr.full_name, hangups.hangouts_pb2.SEGMENT_TYPE_LINK,
                                                       link_target=link))
            if usr.emails:
                segments.append(hangups.ChatMessageSegment(' ('))
                segments.append(hangups.ChatMessageSegment(usr.emails[0], hangups.hangouts_pb2.SEGMENT_TYPE_LINK,
                                                           link_target='mailto:{}'.format(usr.emails[0])))
                segments.append(hangups.ChatMessageSegment(')'))
            segments.append(hangups.ChatMessageSegment(' ... {}'.format(usr.id_.chat_id)))
            segments.append(hangups.ChatMessageSegment('\n', hangups.hangouts_pb2.SEGMENT_TYPE_LINE_BREAK))

    return segments


def hangouts(bot, dummy, *args):
    """retrieve a list of hangouts, supply a search term in args to filter

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        dummy (event.ConversationEvent): not used
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
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        args (str): the new chat title
    """
    await command.run(bot, event, *["convrename", "id:" + event.conv_id,
                                    " ".join(args)])


async def leave(bot, event, *args):
    """leave the current or given conversation

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
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
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        dummys (str): ignored
    """
    await bot.coro_send_message(event.conv, "<b>reloading config.json</b>")
    bot.config.load()

    await bot.coro_send_message(event.conv, "<b>reloading memory.json</b>")
    bot.memory.load()


def quit(bot, event, *dummys):                # pylint:disable=redefined-builtin
    """kill the bot

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        dummys (str): ignored
    """
    logger.warning('HangupsBot killed by user %s from conversation %s',
                   event.user.full_name, event.conv.name)
    bot.stop()


async def config(bot, event, *args):
    """retrieve or edit a config entry

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        args (str): additional words to for a request

    Returns:
        str: request result or None if the output was redirected to a pHO

    Raises:
        Help: invalid request
        KeyError: the given path does not exist
        ValueError: the given value is not a valid json
    """
    async def _test():
        num_parameters = len(parameters)
        text_parameters = []
        last = num_parameters - 1
        for num, token in enumerate(parameters):
            if num == last:
                try:
                    json.loads(token)
                    token += " <b>(valid json)</b>"
                except ValueError:
                    token += " <em>(INVALID)</em>"
            text_parameters.append(str(num + 1) + ": " + token)
        text_parameters.insert(0, "<b>config test</b>")

        if num_parameters == 1:
            text_parameters.append(
                _("<i>note: testing single parameter as json</i>"))
        elif num_parameters < 1:
            await command.unknown_command(bot, event)
            return None

        return "\n".join(text_parameters)

    #TODO(das7pad): refactor into smaller parts and validate the new value/path

    # consume arguments and differentiate beginning of a json array or object
    cmd, *tokens = args or (None,)
    parameters = []
    value = []
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
            parameters.append(token)
        elif state == "json":
            value.append(token)
        else:
            raise Help("unknown state")
    if value:
        parameters.append(" ".join(value))

    if cmd == 'get' or cmd is None:
        config_args = list(parameters)
        value = (bot.config.get_by_path(config_args)
                 if config_args else dict(bot.config))

    elif cmd == 'test':
        return await _test()

    elif cmd == 'set':
        config_args = list(parameters[:-1])
        if len(parameters) >= 2:
            bot.config.set_by_path(config_args, json.loads(parameters[-1]))
            bot.config.save()
            value = bot.config.get_by_path(config_args)
        else:
            await command.unknown_command(bot, event)
            return

    elif cmd == 'append':
        config_args = list(parameters[:-1])
        if len(parameters) < 2:
            await command.unknown_command(bot, event)
            return

        value = bot.config.get_by_path(config_args)
        if isinstance(value, list):
            value.append(json.loads(parameters[-1]))
            bot.config.set_by_path(config_args, value)
            bot.config.save()
        else:
            value = _('append failed on non-list')

    elif cmd == 'remove':
        config_args = list(parameters[:-1])
        if len(parameters) >= 2:
            value = bot.config.get_by_path(config_args)
            if isinstance(value, list):
                value.remove(json.loads(parameters[-1]))
                bot.config.set_by_path(config_args, value)
                bot.config.save()
            else:
                value = _('remove failed on non-list')
        else:
            await command.unknown_command(bot, event)
            return

    else:
        await command.unknown_command(bot, event)
        return

    if value is None:
        value = _('Parameter does not exist!')

    config_path = ' '.join(k for k in ['config'] + config_args)
    output = '\n'.join(['<b>{}:</b>'.format(config_path),
                        json.dumps(value, indent=2, sort_keys=True)])

    if chat_response_private:
        await bot.coro_send_to_user(event.user_id.chat_id, output)
    else:
        return output


def whoami(bot, event, *dummys):
    """retrieve the users G+id

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
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
        dummy (hangupsbot.HangupsBot): the running instance, not used
        event (event.ConversationEvent): a message container
        dummys (str): ignored

    Returns:
        str: a status message
    """
    return _("You are at <b><i>{conv_name}</i></b>, "
             "conv_id = <i>{conv_id}</i>").format(conv_name=event.conv.name,
                                                  conv_id=event.conv_id)
