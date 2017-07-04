# TODO(das7pad) further refactor needed
import logging
import importlib
import sys

from version import __version__
from . import command, get_func_help, Help


logger = logging.getLogger(__name__)

try:
    import resource
except ImportError:
    logger.warning("resource is unavailable on your system")


def _initialise(bot):
    bot.memory.ensure_path(['command_help'])

    bot.register_shared("preprocess_arguments", command.preprocess_arguments)


@command.register
async def help(bot, event, cmd=None, *args):
    """list supported commands, /bot help <command> will show additional details"""
    help_lines = []
    link_to_guide = bot.get_config_suboption(event.conv_id, 'link_to_guide')
    admins_list = bot.get_config_suboption(event.conv_id, 'admins')

    help_chat_id = event.user_id.chat_id
    help_conv_id = event.conv_id
    commands = command.get_available_commands(bot, help_chat_id, help_conv_id)
    commands_admin = commands["admin"]
    commands_nonadmin = commands["user"]

    if (not cmd or
            (cmd == "impersonate" and event.user_id.chat_id in admins_list)):
        if cmd == "impersonate":
            if len(args) == 1:
                help_chat_id = args[0]
            elif len(args) == 2:
                help_chat_id, help_conv_id = args
            else:
                raise Help(_("impersonation: supply chat id and optional "
                             "conversation id"))

            help_lines.append(_('<b>Impersonation:</b>\n'
                                '<b><i>{}</i></b>\n'
                                '<b><i>{}</i></b>\n').format(help_chat_id,
                                                             help_conv_id))

        if commands_nonadmin:
            help_lines.append(_('<b>User commands:</b>'))
            help_lines.append(', '.join(sorted(commands_nonadmin)))

        if link_to_guide:
            help_lines.append('')
            help_lines.append(
                _('<i>For more information, please see: {}</i>').format(
                    link_to_guide))

        if commands_admin:
            help_lines.append('')
            help_lines.append(_('<b>Admin commands:</b>'))
            help_lines.append(', '.join(sorted(commands_admin)))

        help_lines.append("")
        help_lines.append("<b>Command-specific help:</b>")
        help_lines.append("/bot help <command name>")

        bot_aliases = [_alias
                       for _alias in bot._handlers.bot_command
                       if len(_alias) < 9]
        if len(bot_aliases) > 1:
            help_lines.append("")
            help_lines.append("<b>My short-hand names:</b>")
            help_lines.append(', '.join(sorted(bot_aliases)))

    else:
        cmd = cmd.lower()
        if (cmd in command.commands and
                (cmd in commands_admin or cmd in commands_nonadmin)):
            func = command.commands[cmd]
        else:
            await command.unknown_command(bot, event)
            return

        help_lines.append("<b>{}</b>: {}".format(func.__name__,
                                                 get_func_help(bot, cmd, func)))

    await bot.coro_send_to_user_and_conversation(
        event.user.id_.chat_id,
        event.conv_id,
        "\n".join(help_lines), # via private message
        _("<i>{}, I've sent you some help ;)</i>") # public message
        .format(event.user.full_name))

@command.register(admin=True)
def locale(bot, dummy, *args):
    """set bot localisation"""
    if args:
        if bot.set_locale(args[0], reuse="reload" not in args):
            message = _("locale set to: {}".format(args[0]))
        else:
            message = _("locale unchanged")
    else:
        message = _("language code required")

    return message


@command.register
async def ping(bot, event, *args):
    """reply to a ping"""
    await bot.coro_send_message(event.conv_id, 'pong')

    return {"api.response": "pong"}


@command.register
def optout(bot, event, *args):
    """toggle opt-out of bot private messages globally or on a per-conversation basis:

    * /bot optout - toggles global optout on/off, or displays per-conversation optouts
    * /bot optout [name|convid] - toggles per-conversation optout (overrides global settings)
    * /bot optout all - clears per-conversation opt-out and forces global optout"""

    chat_id = event.user.id_.chat_id

    optout = bot.user_memory_get(chat_id, "optout") or False

    target_conv = False
    if args:
        search_string = ' '.join(args).strip()
        if search_string == 'all':
            target_conv = "all"
        else:
            search_results = []
            if (search_string in bot.conversations
                    and bot.conversations[search_string]['type'] == "GROUP"):
                # directly match convid of a group conv
                target_conv = search_string
            else:
                # search for conversation title text, must return single group
                for conv_id, conv_data in bot.conversations.get("text:{0}".format(search_string)).items():
                    if conv_data['type'] == "GROUP":
                        search_results.append(conv_id)
                num_of_results = len(search_results)
                if num_of_results == 1:
                    target_conv = search_results[0]
                else:
                    return _("<i>{}, search did not match a single group "
                             "conversation</i>").format(event.user.full_name)

    if isinstance(optout, list):
        if not target_conv:
            if not optout:
                # force global optout
                optout = True
            else:
                # user will receive list of opted-out conversations
                pass
        elif target_conv.lower() == 'all':
            # convert list optout to bool optout
            optout = True
        elif target_conv in optout:         # pylint: disable=E1135
            # remove existing conversation optout
            optout.remove(target_conv)
        elif target_conv in bot.conversations:
            # optout from a specific conversation
            optout.append(target_conv)
            optout = list(set(optout))
    elif isinstance(optout, bool):
        if not target_conv:
            # toggle global optout
            optout = not optout
        elif target_conv.lower() == 'all':
            # force global optout
            optout = True
        elif target_conv in bot.conversations:
            # convert bool optout to list optout
            optout = [ target_conv ]
        else:
            raise Help(_('no conversation was matched: %s') % target_conv)
    else:
        raise Help(_('unrecognised {} for optout, value={}').format(
            type(optout), optout))

    bot.memory.set_by_path(["user_data", chat_id, "optout"], optout)
    bot.memory.save()

    message = _('<i>{}, you <b>opted-in</b> for bot private messages</i>').format(event.user.full_name)

    if isinstance(optout, bool) and optout:
        message = _('<i>{}, you <b>opted-out</b> from bot private messages</i>').format(event.user.full_name)
    elif isinstance(optout, list) and optout:
        message = _('<i>{}, you are <b>opted-out</b> from the following conversations:\n{}</i>').format(
            event.user.full_name,
            "\n".join([ "* {}".format(bot.conversations.get_name(conv_id))
                        for conv_id in optout ]))

    return message


@command.register
def version(bot, event, *args):
    """get the version of the bot and dependencies (admin-only)"""

    version_info = []

    version_info.append(_("Bot Version: **{}**").format(__version__)) # hangoutsbot
    version_info.append(_("Python Version: **{}**").format(sys.version.split()[0])) # python

    # display extra version information only if user is an admin

    admins_list = bot.get_config_suboption(event.conv_id, 'admins')
    if event.user.id_.chat_id in admins_list:
        # depedencies
        modules = args or [ "aiohttp", "appdirs", "emoji", "hangups", "telepot" ]
        for module_name in modules:
            try:
                _module = importlib.import_module(module_name)
                version_info.append(_("* {} **{}**").format(module_name, _module.__version__))
            except(ImportError, AttributeError):
                pass

    yield from bot.coro_send_message(event.conv, "\n".join(version_info))


@command.register(admin=True)
def resourcememory(*dummys):
    """print basic information about memory usage with resource library"""

    if "resource" not in sys.modules:
        return "<i>resource module not available</i>"

    # http://fa.bianp.net/blog/2013/different-ways-to-get-memory-consumption-or-lessons-learned-from-memory_profiler/
    rusage_denom = 1024.
    if sys.platform == 'darwin':
        # ... it seems that in OSX the output is different units ...
        rusage_denom = rusage_denom * rusage_denom
    mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rusage_denom

    return "<b>memory (resource): {} MB</b>".format(mem)


@command.register_unknown
async def unknown_command(bot, event, *args):
    """handle unknown commands"""
    config_silent = bot.get_config_suboption(event.conv.id_, 'silentmode')
    tagged_silent = "silent" in bot.tags.useractive(event.user_id.chat_id, event.conv.id_)
    if not (config_silent or tagged_silent):

        await bot.coro_send_message( event.conv,
                                      _('{}: Unknown Command').format(event.user.full_name) )


@command.register_blocked
async def blocked_command(bot, event, *args):
    """handle blocked commands"""
    config_silent = bot.get_config_suboption(event.conv.id_, 'silentmode')
    tagged_silent = "silent" in bot.tags.useractive(event.user_id.chat_id, event.conv.id_)
    if not (config_silent or tagged_silent):

        await bot.coro_send_message(event.conv, _('{}: Can\'t do that.').format(
            event.user.full_name))
