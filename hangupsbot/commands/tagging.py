"""bot commands for the integrated tagging"""
# TODO(das7pad) further refactor possible
import logging
import pprint

from . import command, Help


logger = logging.getLogger(__name__)


def _initialise(bot):
    """set defaut config entry"""
    bot.config.set_defaults({"conversations": {}})

def _tagshortcuts(event, type_, conv_id):
    """given type=conv, type=convuser, conv_id=here expands to event.conv_id"""

    if conv_id == "here":
        if type_ not in ["conv", "convuser"]:
            raise Help(_('"here" cannot be used for type "{}"').format(type_))

        conv_id = event.conv_id
        if type_ == "convuser":
            conv_id += "|*"

    return type_, conv_id


@command.register(admin=True)
def tagset(bot, event, *args):
    """set a single tag. usage: tagset <"conv"|"user"|"convuser"> <id> <tag>"""
    if len(args) == 3:
        type_, conv_id, tag = args
        type_, conv_id = _tagshortcuts(event, type_, conv_id)
        if bot.tags.add(type_, conv_id, tag):
            message = _("tagged <b><i>{}</i></b> with <b><i>{}</i></b>".format(
                conv_id, tag))
        else:
            message = _("<b><i>{}</i></b> unchanged".format(conv_id))
    else:
        message = _("<b>supply type, conv_id, tag</b>")
    return message


@command.register(admin=True)
def tagdel(bot, event, *args):
    """remove single tag. usage: tagdel <"conv"|"user"|"convuser"> <id> <tag>"""
    if len(args) == 3:
        type_, conv_id, tag = args
        type_, conv_id = _tagshortcuts(event, type_, conv_id)
        if bot.tags.remove(type_, conv_id, tag):
            message = _("removed <b><i>{}</i></b> from <b><i>{}</i></b>".format(
                tag, conv_id))
        else:
            message = _("<b><i>{}</i></b> unchanged".format(conv_id))
    else:
        message = _("<b>supply type, conv_id, tag</b>")
    return message


@command.register(admin=True)
def tagspurge(bot, event, *args):
    """batch remove tags. usage: tagspurge <"user"|"conv"|"convuser"|"tag"|"usertag"|"convtag"> <id|"ALL">"""
    if len(args) == 2:
        type_, conv_id = args
        type_, conv_id = _tagshortcuts(event, type_, conv_id)
        entries_removed = bot.tags.purge(type_, conv_id)
        message = _("entries removed: <b><i>{}</i></b>".format(entries_removed))
    else:
        message = _("<b>supply type, conv_id</b>")
    return message


@command.register(admin=True)
def tagscommand(bot, _event, *args):
    """display of command tagging information, more complete than plugininfo"""
    if len(args) != 1:
        return Help(_(_("<b>supply command name</b>")))

    command_name = args[0]

    if command_name not in command.commands:
        return _("<b><i>COMMAND: %s</i></b> does not exist") % command_name

    all_tags = set()

    plugin_defined = set()
    if command_name in command.command_tagsets:
        plugin_defined = command.command_tagsets[command_name]
        all_tags = all_tags | plugin_defined

    config_root = set()
    config_commands_tagged = bot.config.get_option('commands_tagged') or {}
    if (command_name in config_commands_tagged and
            config_commands_tagged[command_name]):
        config_root = set(
            [frozenset(value if isinstance(value, list) else [value])
             for value in config_commands_tagged[command_name]])
        all_tags = all_tags | config_root

    def _extend_tage(source, all_tags):
        """extend the tags with command tags from the given source"""
        if command_name not in source or not source[command_name]:
            return

        items = set([frozenset(value if isinstance(value, list) else [value])
                     for value in source[command_name]])
        return all_tags | items

    config_conv = {}
    for convid in bot.config["conversations"]:
        path = ["conversations", convid, "commands_tagged"]
        if bot.config.exists(path):
            conv_tagged = bot.config.get_by_path(path)
            if command_name in conv_tagged and conv_tagged[command_name]:
                config_conv[convid] = set(
                    [frozenset(value if isinstance(value, list) else [value])
                     for value in conv_tagged[command_name]])
                all_tags = all_tags | config_conv[convid]

    tags = {}
    for match in all_tags:
        text_match = ", ".join(sorted(match))

        if text_match not in tags:
            tags[text_match] = []

        if match in plugin_defined:
            tags[text_match].append("plugin")
        if match in config_root:
            tags[text_match].append("config: root")
        for convid, tagsets in config_conv.items():
            if match in tagsets:
                tags[text_match].append("config: {}".format(convid))

    lines = []
    for text_tags in sorted(tags):
        lines.append("[ {} ]".format(text_tags))
        for source in tags[text_tags]:
            lines.append("... {}".format(source))

    if not lines:
        return _("<b><i>COMMAND: {}</i></b> has no tags".format(command_name))

    lines.insert(0, _("<b><i>COMMAND: {}</i></b>, match <b>ANY</b>:").format(
        command_name))

    return "\n".join(lines)


@command.register(admin=True)
def tagindexdump(bot, _event, *_args):
    """dump raw contents of tags indices"""
    printer = pprint.PrettyPrinter(indent=2)
    printer.pprint(bot.tags.indices)

    chunks = []
    for relationship in bot.tags.indices:
        lines = [_("index: <b><i>{}</i></b>").format(relationship)]
        for key, items in bot.tags.indices[relationship].items():
            lines.append(_("key: <i>{}</i>").format(key))
            for item in items:
                lines.append("... <i>{}</i>".format(item))
        if len(lines) == 0:
            continue
        chunks.append("\n".join(lines))

    if len(chunks) == 0:
        chunks = [_("<b>no entries to list</b>")]

    return "\n\n".join(chunks)


@command.register(admin=True)
def tagsconv(bot, event, *args):
    """get tag assignments for conversation (default: current conversation). usage: tagsconv [here|<conv id>]"""
    if len(args) == 1:
        conv_id = args[0]
    else:
        conv_id = event.conv_id

    if conv_id == "here":
        conv_id = event.conv_id

    active_conv_tags = bot.tags.convactive(conv_id)
    if active_conv_tags:
        message_taglist = ", ".join(["<i>{}</i>".format(tag)
                                     for tag in active_conv_tags])
    else:
        message_taglist = "<em>no tags returned</em>"

    return "<b><i>{}</i></b>: {}".format(conv_id, message_taglist)


@command.register(admin=True)
def tagsuser(bot, event, *args):
    """get tag assignments for a user in an (optional) conversation. usage: tagsuser <user id> [<conv id>]"""
    if len(args) == 1:
        conv_id = "*"
        chat_id = args[0]
    elif len(args) == 2:
        conv_id = args[1]
        chat_id = args[0]
    else:
        return _("<b>supply chat_id, optional conv_id</b>")

    if conv_id == "here":
        conv_id = event.conv_id

    active_user_tags = bot.tags.useractive(chat_id, conv_id)
    if active_user_tags:
        message_taglist = ", ".join(["<i>{}</i>".format(tag)
                                     for tag in active_user_tags])
    else:
        message_taglist = "<em>no tags returned</em>"

    return "<b><i>{}</i></b>@<b><i>{}</i></b>: {}".format(chat_id, conv_id,
                                                          message_taglist)


@command.register(admin=True)
def tagsuserlist(bot, event, *args):
    """get tag assignments for all users in a conversation, filtered by (optional) taglist. usage: tagsuserlist <conv id> [<tag name> [<tag name>] [...]]"""
    if len(args) == 1:
        conv_id = args[0]
        filter_tags = False
    elif len(args) > 1:
        conv_id = args[0]
        filter_tags = args[1:]
    else:
        return _("<b>supply conv_id, optional tag list</b>")

    if conv_id == "here":
        conv_id = event.conv_id

    users_to_tags = bot.tags.userlist(conv_id, filter_tags)

    lines = []
    for chat_id, active_user_tags in users_to_tags.items():
        if not active_user_tags:
            active_user_tags = [_("<em>no tags returned</em>")]

        lines.append("<b><i>{}</i></b>: <i>{}</i>".format(
            chat_id, ", ".join(active_user_tags)))

    if len(lines) == 0:
        lines = [_("<b>no users found</b>")]

    return "\n".join(lines)
