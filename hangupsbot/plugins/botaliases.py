"""aliases for the bot"""
import logging

from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    "botalias": _("show, add and remove bot command aliases\nshow:\n  "
                  "{bot_cmd} botalias\nadd:\n  {bot_cmd} botalias <single "
                  "alias>\nremove  {bot_cmd} botalias remove <single alias or "
                  "multiple aliases separated by blanks>"),
}


def _initialise(bot):
    """load in bot aliases from memory, create defaults if none"""

    if bot.memory.exists(["bot.command_aliases"]):
        bot_command_aliases = bot.memory["bot.command_aliases"]
    else:
        myself = bot.user_self()
        # basic
        bot_command_aliases = ["/bot"]

        # /<first name fragment>
        first_fragment = myself["full_name"].split()[0].lower()
        if first_fragment != "unknown":
            alias_first_name = "/" + first_fragment
            bot_command_aliases.append(alias_first_name)

        # /<chat_id>
        bot_command_aliases.append("/" + myself["chat_id"])

        bot.memory.set_by_path(["bot.command_aliases"], bot_command_aliases)
        bot.memory.save()

    if not isinstance(bot_command_aliases, list):
        bot_command_aliases = []

    if not bot_command_aliases:
        bot.append("/bot")

    # pylint:disable=protected-access
    bot._handlers.bot_command = bot_command_aliases
    # pylint:enable=protected-access
    logger.info("aliases: %s", bot_command_aliases)

    plugins.register_user_command([
        "botalias",
    ])
    plugins.register_help(HELP)


def botalias(bot, event, *args):
    """update the botaliases for bot commands

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): the aliases to add/remove

    Returns:
        str: command output
    """
    # pylint:disable=protected-access
    _aliases = bot._handlers.bot_command
    # pylint:enable=protected-access
    if not args:
        return _("<i>bot aliases: {}</i>").format(
            ", ".join(_aliases))

    admins_list = bot.config["admins"]

    if event.user_id.chat_id not in admins_list:
        return _("<i>you are not authorised to change the bot alias</i>")

    if len(args) == 1:
        # add alias
        if args[0].lower() not in _aliases:
            _aliases.append(args[0].lower())
    else:
        # remove aliases, supply list to remove more than one
        if args[0].lower() == "remove":
            for _alias in args[1:]:
                _aliases.remove(_alias.lower())

    if not _aliases:
        _aliases.append("/bot")

    bot.memory.set_by_path(["bot.command_aliases"], _aliases)
    bot.memory.save()

    return botalias(bot, event)  # run with no arguments
