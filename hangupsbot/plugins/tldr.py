import logging
import time

from hangupsbot import plugins
from hangupsbot.commands import Help

logger = logging.getLogger(__name__)

TLDR_ECHO_OPTIONS = [
    "PM",
    "GROUP",
    "GLOBAL"
]

HELP = {
    'gettldr': _('Get the tl;dr of a conversation into your private chat with '
                 'the bot.'),

    'tldrecho': _('defines whether the tldr is sent as a private message or '
                  'into the main chat'),

    'tldr': _(
        'read and manage tldr entries for a given conversation\n\n'
        '- {bot_cmd} tldr <number>\n'
        '   retrieve a specific numbered entry\n'
        '- {bot_cmd} tldr <text>\n'
        '   add <text> as an entry\n'
        '- {bot_cmd} tldr edit <number> <text>\n'
        '   replace the specified entry with the new <text>\n'
        '- {bot_cmd} tldr clear <number>\n'
        '   clear specified numbered entry\n'
        '   <i>special case: {bot_cmd} tldr clear all\n'
        '     clear all entries</i>')
}

def _initialise(bot):
    plugins.register_user_command(["tldr", "gettldr"])
    plugins.register_admin_command(["tldrecho"])
    plugins.register_help(HELP)
    bot.register_shared("plugin_tldr_shared", tldr_shared)

    # Set the global option
    if not bot.config.exists(['tldr_echo']):
        bot.config.set_by_path(["tldr_echo"], 1) # TLDR_ECHO_OPTIONS[1] is "GROUP"
        bot.config.save()


async def gettldr(bot, event, *args):
    """Forward the tl;dr of a conversation into the private chat with the user

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message content wrapper
        args (str): the query params

    Returns:
        str: status message
    """
    query = ''.join(args)
    if not query:
        return _('Specify a conversation name')

    try:
        conv_id = bot.call_shared('alias2convid', query)
    except KeyError:
        conv_id = None

    if conv_id is not None:
        conversations = (conv_id,)
    else:
        if ':' not in query:
            query = 'text:' + query

        conversations = tuple(bot.conversations.get(query))

    chat_id = event.user_id.chat_id
    if chat_id not in bot.config['admins']:
        # verify that the user is member in the requested conversation
        is_member_in = []
        for conv_id in conversations:
            users = await bot.sync.get_users_in_conversation(
                conv_id, profilesync_only=True, return_flat=True,
            )
            if any(user.id_.chat_id == chat_id for user in users):
                is_member_in.append(conv_id)

        conversations = tuple(is_member_in)

    if not conversations:
        return _('The query returned no conversations for you')

    if len(conversations) > 1:
        names = '- '
        names += '\n- '.join(bot.conversations.get_name(conv_id, 'unknown')
                             for conv_id in conversations)
        return _('The query returned too many conversations:\n{names}').format(
            names=names,
        )

    conv_id = conversations[0]
    text = _('TL;DR of "{name}":\n{text}').format(
        name=bot.conversations.get_name(conv_id, 'unknown'),
        text=tldr_base(bot, conv_id, ())[0],
    )
    await bot.coro_send_to_user(event.user_id.chat_id, text)
    return None


def tldrecho(bot, event, *dummys):
    """defines whether the tldr is sent as a private message instead"""

    # If no memory entry exists for the conversation, create it.
    if not bot.memory.exists(['conversations']):
        bot.memory.set_by_path(['conversations'], {})
    if not bot.memory.exists(['conversations', event.conv_id]):
        bot.memory.set_by_path(['conversations', event.conv_id], {})

    if bot.memory.exists(['conversations', event.conv_id, 'tldr_echo']):
        new_tldr = (bot.memory.get_by_path(['conversations', event.conv_id, 'tldr_echo']) + 1)%3
    else:
        # No path was found. Is this your first setup?
        new_tldr = 0

    if TLDR_ECHO_OPTIONS[new_tldr] == "GLOBAL":
        # Update the tldr_echo setting
        bot.memory.set_by_path(['conversations', event.conv_id, 'tldr_echo'], new_tldr)
    else:
        # If setting is global then clear the conversation memory entry
        conv_settings = bot.memory.get_by_path(['conversations', event.conv_id])
        del conv_settings['tldr_echo'] # remove setting
        bot.memory.set_by_path(['conversations', event.conv_id], conv_settings)

    bot.memory.save()

    # Echo the current tldr setting
    message = '<b>TLDR echo setting for this hangout has been set to {0}.</b>'.format(TLDR_ECHO_OPTIONS[new_tldr])
    logger.debug("%s (%s) has toggled the tldrecho in '%s' to %s",
                 event.user.full_name, event.user.id_.chat_id, event.conv_id,
                 TLDR_ECHO_OPTIONS[new_tldr])

    return message


async def tldr(bot, event, *args):
    """read and manage tldr entries for a given conversation"""

    # If no memory entry exists for the conversation, create it.
    if not bot.memory.exists(['conversations']):
        bot.memory.set_by_path(['conversations'], {})
    if not bot.memory.exists(['conversations', event.conv_id]):
        bot.memory.set_by_path(['conversations', event.conv_id], {})

    # Retrieve the current tldr echo status for the hangout.
    if bot.memory.exists(['conversations', event.conv_id, 'tldr_echo']):
        tldr_echo = bot.memory.get_by_path(['conversations', event.conv_id, 'tldr_echo'])
    else:
        tldr_echo = bot.config.get_option("tldr_echo")

    message, display = tldr_base(bot, event.conv_id, list(args))

    if display is True and TLDR_ECHO_OPTIONS[tldr_echo] == 'PM':
        await bot.coro_send_to_user_and_conversation(
            event.user.id_.chat_id, event.conv_id, message,
            _("<i>{}, I've sent you the info in a PM</i>").format(
                event.user.full_name))
    else:
        await bot.coro_send_message(event.conv_id, message)


def tldr_shared(bot, args):
    """Shares tldr functionality with other plugins

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        args (dict): a dictionary which holds arguments.
            Must contain 'params' (tldr command parameters)
            and 'conv_id' (Hangouts conv_id)

    Returns:
        str: a status message with the tldr of the conversation

    Raises:
        Help: invalid arguments specified
    """
    if not isinstance(args, dict):
        raise Help("args must be a dictionary")

    if 'params' not in args:
        raise Help("'params' key missing in args")

    if 'conv_id' not in args:
        raise Help("'conv_id' key missing in args")

    params = args['params']
    conv_id = args['conv_id']

    return_data, dummy = tldr_base(bot, conv_id, params)

    return return_data


def tldr_base(bot, conv_id, parameters):
    # parameters = list(args)

    # If no memory entry exists, create it.
    if not bot.memory.exists(['tldr']):
        bot.memory.set_by_path(['tldr'], {})
    if not bot.memory.exists(['tldr', conv_id]):
        bot.memory.set_by_path(['tldr', conv_id], {})

    conv_tldr = bot.memory.get_by_path(['tldr', conv_id])

    display = False
    if not parameters:
        display = True
    elif len(parameters) == 1 and parameters[0].isdigit():
        display = int(parameters[0]) - 1

    if display is not False:
        # Display all messages or a specific message
        html = []
        for num, timestamp in enumerate(sorted(conv_tldr, key=float)):
            if display is True or display == num:
                html.append(_("{}. {} <b>{} ago</b>").format(str(num + 1),
                                                             conv_tldr[timestamp],
                                                             _time_ago(float(timestamp))))

        if not html:
            html.append(_("TL;DR not found."))
            display = False
        else:
            html.insert(0, _("<b>TL;DR ({} stored):</b>").format(len(conv_tldr)))
        message = _("\n".join(html))

        return message, display


    conv_id_list = [conv_id]

    # Check to see if sync is active
    syncouts = bot.config.get_option('sync_rooms')

    # If yes, then find out if the current room is part of one.
    # If it is, then add the rest of the rooms to the list of conversations to process
    if syncouts:
        for sync_room_list in syncouts:
            if conv_id in sync_room_list:
                for conv in sync_room_list:
                    if not conv in conv_id_list:
                        conv_id_list.append(conv)


    if parameters[0] == "clear":
        if len(parameters) == 2 and parameters[1].isdigit():
            sorted_keys = sorted(list(conv_tldr.keys()), key=float)
            key_index = int(parameters[1]) - 1
            if key_index < 0 or key_index >= len(sorted_keys):
                message = _("TL;DR #{} not found.").format(parameters[1])
            else:
                popped_tldr = conv_tldr.pop(sorted_keys[key_index])
                for conv in conv_id_list:
                    bot.memory.set_by_path(['tldr', conv], conv_tldr)
                bot.memory.save()
                message = _('TL;DR #{} removed - "{}"').format(parameters[1], popped_tldr)
        elif len(parameters) == 2 and parameters[1].lower() == "all":
            for conv in conv_id_list:
                bot.memory.set_by_path(['tldr', conv], {})
            bot.memory.save()
            message = _("All TL;DRs cleared.")
        else:
            message = _("Nothing specified to clear.")

        return message, display

    elif parameters[0] == "edit":
        if len(parameters) > 2 and parameters[1].isdigit():
            sorted_keys = sorted(list(conv_tldr.keys()), key=float)
            key_index = int(parameters[1]) - 1
            if key_index < 0 or key_index >= len(sorted_keys):
                message = _("TL;DR #{} not found.").format(parameters[1])
            else:
                edited_tldr = conv_tldr[sorted_keys[key_index]]
                text = ' '.join(parameters[2:len(parameters)])
                conv_tldr[sorted_keys[key_index]] = text
                for conv in conv_id_list:
                    bot.memory.set_by_path(['tldr', conv], conv_tldr)
                bot.memory.save()
                message = _('TL;DR #{} edited - "{}" -> "{}"').format(parameters[1], edited_tldr, text)
        else:
            message = _('Unknown Command at "tldr edit."')

        return message, display

    elif parameters[0]:  ## need a better looking solution here
        text = ' '.join(parameters)
        if text:
            # Add message to list
            conv_tldr[str(time.time())] = text
            for conv in conv_id_list:
                bot.memory.set_by_path(['tldr', conv], conv_tldr)
            bot.memory.save()
            message = _('<em>{}</em> added to TL;DR. Count: {}').format(text, len(conv_tldr))

            return message, display

    return '', 0


def _time_ago(timestamp):
    time_difference = time.time() - timestamp
    if time_difference < 60:  # seconds
        return _("{}s").format(int(time_difference))
    if time_difference < 60 * 60:  # minutes
        return _("{}m").format(int(time_difference / 60))
    if time_difference < 60 * 60 * 24:  # hours
        return _("{}h").format(int(time_difference / (60 * 60)))
    return _("{}d").format(int(time_difference / (60 * 60 * 24)))
