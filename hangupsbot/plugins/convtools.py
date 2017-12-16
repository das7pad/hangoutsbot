"""commands to add/kick users from a conversation or create new conversations"""

import asyncio
import logging

import hangups

from hangupsbot import commands
from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    "addusers": _("adds user(s) into a chat\nUsage: {bot_cmd} addusers <user id"
                  "(s)> [into <chat id>]"),

    "addme": _("add yourself into a chat\nUsage: {bot_cmd} addme <conv id>"),

    "createconversation": _("create a new conversation with the bot and the "
                            "specified user(s)\nUsage: {bot_cmd} "
                            "createconversation <user id(s)>"),

    "refresh": _("refresh a chat\nUsage: {bot_cmd} refresh\n[conversation] "
                 "<conversation id> [<without|remove> <user ids, "
                 "space-separated if more than one>] [<with|add> <user id(s)>] "
                 "[quietly] [norename]"),

    "kick": _("create a new conversation without certain users\nUsage: "
              "{bot_cmd} kick\n[<conversation id, current if not specified>] "
              "[<user ids, space-separated if more than one>] [quietly]"),

    "realkick": _("remove users from a conversation\nUsage: {bot_cmd} realkick "
                  "[<optional conversation id, current if not specified>] "
                  "[<user ids, space-separated if more than one>]"),
}

def _initialise():
    """register commands and their user help"""
    plugins.register_admin_command(["addme", "addusers", "createconversation",
                                    "refresh", "kick", "realkick"])
    plugins.register_help(HELP)

async def _batch_add_users(bot, conv_id, chat_ids, batch_max=20):
    """add users to a conversation but split the queue in parts

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        conv_id (str): conversation identifier
        chat_ids (list[str]): a list of G+ User Ids
        batch_max (int): number of users to be added at once

    Returns:
        int: the number of new users in the conversation
    """
    chat_ids = list(set(chat_ids))

    not_there = []
    for chat_id in chat_ids:
        if chat_id not in bot.conversations[conv_id]["participants"]:
            not_there.append(chat_id)
        else:
            logger.debug("addusers: user %s already in %s", chat_id, conv_id)
    chat_ids = not_there

    users_added = 0
    chunks = [chat_ids[i:i+batch_max]
              for i in range(0, len(chat_ids), batch_max)]
    for number, partial_list in enumerate(chunks):
        logger.info("batch add users: %s/%s %s user(s) into %s",
                    number+1, len(chunks), len(partial_list), conv_id)

        await bot.add_user(
            hangups.hangouts_pb2.AddUserRequest(
                request_header=bot.get_request_header(),
                invitee_id=[hangups.hangouts_pb2.InviteeID(gaia_id=chat_id)
                            for chat_id in partial_list],
                event_request_header=hangups.hangouts_pb2.EventRequestHeader(
                    conversation_id=hangups.hangouts_pb2.ConversationId(
                        id=conv_id),
                    client_generated_id=bot.get_client_generated_id())))

        users_added = users_added + len(partial_list)
        await asyncio.sleep(0.5)

    return users_added

async def _batch_remove_users(bot, target_conv, chat_ids):
    """remove a list of users from a given conversation

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        target_conv (str): conversation identifier
        chat_ids (iterable): with strings, G+Ids

    Returns:
        set[str]: user ids that could not be removed
    """
    chat_ids = set(chat_ids)
    remove = set()
    for chat_id in chat_ids:
        if chat_id in bot.conversations[target_conv]["participants"]:
            remove.add(chat_id)

    for chat_id in remove:
        await bot.remove_user(
            hangups.hangouts_pb2.RemoveUserRequest(
                request_header=bot.get_request_header(),
                event_request_header=hangups.hangouts_pb2.EventRequestHeader(
                    conversation_id=hangups.hangouts_pb2.ConversationId(
                        id=target_conv),
                    client_generated_id=bot.get_client_generated_id()),
                participant_id=hangups.hangouts_pb2.ParticipantId(
                    gaia_id=chat_id)))

        await asyncio.sleep(0.5)
    return chat_ids - remove

async def addusers(bot, event, *args):
    """add users from a conversation

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        args (str):additional words passed to the command

    Raises:
        commands.Help: invalid request
    """
    list_add = []
    target_conv = event.conv_id

    state = ["add_user"]

    for parameter in args:
        if parameter == "into":
            state.append("target_conv")
        else:
            if state[-1] == "add_user":
                list_add.append(parameter)
            elif state[-1] == "target_conv":
                target_conv = parameter
                state.pop()
            else:
                raise commands.Help("UNKNOWN STATE: {}".format(state[-1]))

    list_add = list(set(list_add))
    if list_add:
        added = await _batch_add_users(bot, target_conv, list_add)
        logger.info("addusers: %s added to %s", added, target_conv)

async def addme(bot, event, *args):
    """let a user add himself to a conversation

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        args (str):additional words passed to the command

    Raises:
        commands.Help: invalid request
    """
    if not args:
        raise commands.Help(_("supply the id of the conversation to join"))

    if args[0] not in bot.conversations:
        raise commands.Help(_("I am not attending this conversation"))

    await addusers(bot, event, *[event.user_id.chat_id, "into", args[0]])

async def createconversation(bot, dummy, *args):
    """create a new conversation with given users

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        dummy (event.ConversationEvent): not used
        args (str):additional words passed to the command

    Returns:
        tuple[str]: target conversation, command output

    Raises:
        commands.Help: invalid request
    """
    user_ids = [chat_id for chat_id in set(args)
                if len(chat_id) == 21 and chat_id.isdigit()]

    if not user_ids:
        raise commands.Help('supply G+ Ids to add')

    logger.info("createconversation: %s", user_ids)

    _response = await bot.create_conversation(
        hangups.hangouts_pb2.CreateConversationRequest(
            request_header=bot.get_request_header(),
            type=hangups.hangouts_pb2.CONVERSATION_TYPE_GROUP,
            client_generated_id=bot.get_client_generated_id(),
            invitee_id=[hangups.hangouts_pb2.InviteeID(gaia_id=chat_id)
                        for chat_id in user_ids]))
    new_conversation_id = _response.conversation.conversation_id.id

    return new_conversation_id, _("<i>conversation created</i>")

async def refresh(bot, event, *args):
    """recreate a conversation and remove or add certain users

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        args (str):additional words passed to the command

    Returns:
        str: command output

    Raises:
        commands.Help: invalid request
    """
    # TODO(das7pad): refactor into smaller functions
    parameters = list(args)

    test = False
    quietly = False
    source_conv = False
    rename_old = True
    list_removed = []
    list_added = []

    state = ["conversation"]

    for parameter in parameters:
        if parameter == _("remove") or parameter == _("without"):
            state.append("remove_user")
        elif parameter == _("add") or parameter == _("with"):
            state.append("add_user")
        elif parameter == _("conversation"):
            state.append("conversation")
        elif parameter == _("quietly"):
            quietly = True
            rename_old = False
        elif parameter == _("test"):
            test = True
        elif parameter == _("norename"):
            rename_old = False
        else:
            if state[-1] == "add_user":
                list_added.append(parameter)
                if parameter in list_removed:
                    list_removed.remove(parameter)

            elif state[-1] == "remove_user":
                list_removed.append(parameter)
                if parameter in list_added:
                    list_added.remove(parameter)

            elif state[-1] == "conversation":
                source_conv = parameter

            else:
                raise commands.Help("UNKNOWN STATE: {}".format(state[-1]))

    list_removed = list(set(list_removed))

    if not source_conv:
        raise commands.Help("conversation id not supplied")

    if source_conv not in bot.conversations:
        raise commands.Help(_("conversation {} not found").format(source_conv))

    if bot.conversations[source_conv]["type"] != "GROUP":
        raise commands.Help(_("conversation %s is not a GROUP") % source_conv)

    new_title = bot.conversations.get_name(source_conv)
    old_title = _("[DEFUNCT] {}".format(new_title))

    text_removed_users = []
    for user in bot.get_users_in_conversation(source_conv):
        if user.id_.chat_id not in list_removed:
            list_added.append(user.id_.chat_id)
        else:
            text_removed_users.append(
                "<i>{}</i> ({})".format(user.full_name, user.id_.chat_id))

    list_added = list(set(list_added))

    logger.debug("refresh: from conversation %s removed %s added %s",
                 source_conv, len(list_removed), len(list_added))

    if test:
        return _("<b>refresh:</b> {}\n"
                 "<b>rename old: {}</b>\n"
                 "<b>removed {}:</b> {}\n"
                 "<b>added {}:</b> {}").format(
                     source_conv,
                     old_title if rename_old else _("<em>unchanged</em>"),
                     len(text_removed_users),
                     ", ".join(text_removed_users) or _("<em>none</em>"),
                     len(list_added),
                     " ".join(list_added) or _("<em>none</em>"))

    if len(list_added) <= 1:
        return _("<b>nobody to add in the new conversation</b>")

    _response = await bot.create_conversation(
        hangups.hangouts_pb2.CreateConversationRequest(
            request_header=bot.get_request_header(),
            type=hangups.hangouts_pb2.CONVERSATION_TYPE_GROUP,
            client_generated_id=bot.get_client_generated_id(),
            invitee_id=[]))
    new_conversation_id = _response.conversation.conversation_id.id

    await bot.coro_send_message(new_conversation_id,
                                _("<i>refreshing group...</i>\n"))
    await asyncio.sleep(1)
    await _batch_add_users(bot, new_conversation_id, list_added)
    await bot.coro_send_message(new_conversation_id,
                                _("<i>all users added</i>\n"))
    await asyncio.sleep(1)
    await commands.command.run(
        bot, event, *["convrename", "id:" + new_conversation_id, new_title])

    if rename_old:
        await commands.command.run(
            bot, event, *["convrename", "id:" + source_conv, old_title])

    if not quietly:
        await bot.coro_send_message(source_conv,
                                    _("<i>group has been obsoleted</i>"))

    return _("refreshed: <b><pre>{}</pre></b> "
             "(original id: <pre>{}</pre>).\n"
             "new conversation id: <b><pre>{}</pre></b>.\n"
             "removed {}: {}").format(new_title,
                                      source_conv,
                                      new_conversation_id,
                                      len(text_removed_users),
                                      (", ".join(text_removed_users)
                                       or _("<em>none</em>")))


async def kick(bot, event, *args):
    """refresh the a conversation without certain users

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        args (str):additional words passed to the command
    """
    parameters = list(args)

    source_conv = event.conv_id
    remove = set()
    test = False
    quietly = False

    for parameter in parameters:
        if parameter in bot.conversations[source_conv]["participants"]:
            remove.add(parameter)
        elif parameter in bot.conversations:
            source_conv = parameter
        elif parameter == _("test"):
            test = True
        elif parameter == _("quietly"):
            quietly = True
        else:
            raise commands.Help(_("supply optional conversation id and valid "
                                  "user ids to kick"))

    if not remove:
        raise commands.Help(_("supply at least one valid user id to kick"))

    arguments = ["refresh", source_conv, "without"] + list(remove)

    if test:
        arguments.append(_("test"))

    if quietly:
        arguments.append(_("quietly"))

    await commands.command.run(bot, event, *arguments)

async def realkick(bot, event, *args):
    """remove users from a conversation

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        args (str):additional words passed to the command

    Returns:
        str: command output
    """
    chat_ids = []
    conv_id = event.conv_id
    for item in args:
        if item in bot.conversations:
            conv_id = item
        elif item.isdigit():
            chat_ids.append(item)
        else:
            return _("invalid G+ or Conversation ID {}").format(item)

    failed = await _batch_remove_users(bot, conv_id, chat_ids)
    if failed:
        return _("These users are not in this conversation, try another one."
                 "\n{}").format(", ".join(failed))
