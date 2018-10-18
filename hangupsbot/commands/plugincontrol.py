# TODO(das7pad) refactor needed
import logging

from hangupsbot import plugins
from hangupsbot.commands import (
    Help,
    command,
)
from hangupsbot.sinks import aiohttp_list


logger = logging.getLogger(__name__)


def _initialise():
    pass  # prevents commands from being automatically added


def function_name(func):
    try:
        # standard function
        return func.__name__
    except AttributeError:
        try:
            # lambda
            return func.func_name
        except AttributeError:
            try:
                # functools.partial
                return function_name(func.func)
            except AttributeError:
                return '<unknown>'


@command.register(admin=True)
def plugininfo(dummy0, dummy1, *args):
    """dumps plugin information"""

    text_plugins = []

    for module_path, plugin in plugins.tracking.list.items():
        lines = []
        if (args and ("module" in plugin["metadata"] and
                      args[0] not in plugin["metadata"]["module"]
                      or args[0] not in module_path)):
            continue
        lines.append("<b>[ {} ]</b>".format(plugin["metadata"]["module.path"]))

        # admin commands
        if plugin["commands"]["admin"]:
            lines.append("<b>admin commands:</b> <pre>{}</pre>".format(
                ", ".join(plugin["commands"]["admin"])))

        # user-only commands
        user_only_commands = list(
            set(plugin["commands"]["user"]) - set(plugin["commands"]["admin"]))
        if user_only_commands:
            lines.append("<b>user commands:</b> <pre>{}</pre>".format(
                ", ".join(user_only_commands)))

        # handlers
        if plugin["handlers"]:
            lines.append("<b>handlers:</b>")
            lines.append("\n".join([
                "... <b><pre>{}</pre></b> (<pre>{}</pre>, p={})".format(
                    function_name(f[0]), f[1], str(f[2]))
                for f in plugin["handlers"]]))

        # shared
        if plugin["shared"]:
            lines.append("<b>shared:</b> " + ", ".join(
                ["<pre>{}</pre>".format(function_name(f[1])) for f in
                 plugin["shared"]]))

        # aiohttp.web
        if plugin["aiohttp.web"]:
            lines.append("<b>aiohttp.web:</b>")
            filtered = aiohttp_list(plugin["aiohttp.web"])
            if filtered:
                lines.append('\n'.join(
                    ['... {}'.format(constructors[0].sockets[0].getsockname())
                     for constructors in filtered]))
            else:
                lines.append('<em>no running aiohttp.web listeners</em>')

        # tagged
        if plugin["commands"]["tagged"]:
            lines.append("<b>tagged via plugin module:</b>")
            for command_name, type_tags in plugin["commands"]["tagged"].items():
                if 'admin' in type_tags:
                    plugin_tags = type_tags['admin']
                else:
                    plugin_tags = type_tags['user']

                matches = []
                for tags in plugin_tags:
                    if isinstance(tags, frozenset):
                        matches.append("[ {} ]".format(', '.join(tags)))
                    else:
                        matches.append(tags)

                lines.append("... <b><pre>{}</pre></b>: <pre>{}</pre>".format(
                    command_name, ', '.join(matches)))

        # command: argument preprocessors
        if plugin["commands"]["argument.preprocessors"]:
            lines.append("<b>command preprocessor groups:</b> ")
            lines.append(", ".join(plugin["commands"]["argument.preprocessors"]))

        text_plugins.append("\n".join(lines))

    if text_plugins:
        message = "\n".join(text_plugins)
    else:
        message = "nothing to display"

    return message


def _compose_load_message(module_path, result):
    """get a formatted message

    Args:
        module_path (str): plugin path
        result (str): result of the load function

    Returns:
        str: the formatted message
    """
    return "<b><i>%s</i></b> : <b>%s</b>" % (module_path, result)


@command.register(admin=True)
async def pluginunload(bot, event, *args):
    """unloads a previously unloaded plugin, requires plugins. prefix"""

    if args:
        module_path = args[0]

        try:
            await plugins.unload(bot, module_path)
        except plugins.NotLoaded:
            result = _("not previously loaded")
        else:
            result = _("unloaded")

        message = _compose_load_message(module_path, result)

    else:
        message = _("<b>module path required</b>")

    await bot.coro_send_message(event.conv_id, message)


@command.register(admin=True)
async def pluginload(bot, event, *args):
    """loads a previously unloaded plugin, requires plugins. prefix"""

    if args:
        module_path = args[0]

        try:
            if await plugins.load(bot, module_path):
                result = _("loaded")
            else:
                result = _("failed")

        except plugins.AlreadyLoaded:
            result = _("already loaded")
        except plugins.Protected:
            result = _("protected")

        message = _compose_load_message(module_path, result)

    else:
        message = _("<b>module path required</b>")

    await bot.coro_send_message(event.conv_id, message)


@command.register(admin=True)
async def pluginreload(bot, event, *args):
    """reloads a previously loaded plugin, requires plugins. prefix"""

    if args:
        module_path = args[0]

        try:
            await plugins.unload(bot, module_path)
        except plugins.NotLoaded:
            result = _("not previously loaded")
        else:
            if await plugins.load(bot, module_path):
                result = _("reloaded")
            else:
                result = _("failed reload")

        message = _compose_load_message(module_path, result)

    else:
        message = _("<b>module path required</b>")

    await bot.coro_send_message(event.conv_id, message)


@command.register(admin=True)
def getplugins(bot, *dummys):
    """list all plugins loaded by the bot, and all available plugins"""

    config_plugins = bot.config.get_by_path(["plugins"]) or False
    if not isinstance(config_plugins, list):
        return _("this command only works with manually-configured plugins key "
                 "in config.json")

    lines = []
    all_plugins = plugins.retrieve_all_plugins(allow_underscore=True) or []
    loaded_plugins = plugins.get_configured_plugins(bot) or []

    lines.append(
        "**{} loaded plugins (config.json)**".format(len(loaded_plugins)))

    for _plugin in sorted(loaded_plugins):
        lines.append("* {}".format(_plugin.replace("_", "\\_")))

    lines.append("**{} available plugins**".format(len(all_plugins)))

    for _plugin in sorted(all_plugins):
        if _plugin not in loaded_plugins:
            lines.append("* {}".format(_plugin.replace("_", "\\_")))

    return "\n".join(lines)


def _strip_plugin_path(path):
    """remove "plugins." prefix if it exist"""
    return path[8:] if path.startswith("plugins.") else path


@command.register(admin=True)
async def removeplugin(bot, dummy, *args):
    """unloads a plugin from the bot and removes it from the config, does not
    require plugins. prefix"""

    if not args:
        raise Help(_('plugin name is missing!'))
    plugin = args[0]

    config_plugins = bot.config.get_by_path(["plugins"]) or False
    if not isinstance(config_plugins, list):
        return _("this command only works with manually-configured plugins key "
                 "in config.json")

    lines = []
    loaded_plugins = plugins.get_configured_plugins(bot) or []
    all_plugins = plugins.retrieve_all_plugins(allow_underscore=True)

    lines.append("**remove plugin: {}**".format(plugin.replace("_", "\\_")))

    plugin = _strip_plugin_path(plugin)

    if not plugin:
        return "invalid plugin name"

    if plugin not in all_plugins:
        return "plugin does not exist: {}".format(plugin.replace("_", "\\_"))

    if plugin in loaded_plugins:
        module_path = "plugins.{}".format(plugin)
        escaped_module_path = module_path.replace("_", "\\_")
        try:
            await plugins.unload(bot, module_path)
            lines.append('* **unloaded: {}**'.format(escaped_module_path))
        except (RuntimeError, KeyError) as err:
            lines.append(
                '* error unloading {}: {}'.format(escaped_module_path, str(err)))
    else:
        lines.append('* not loaded on bot start')

    if plugin in config_plugins:
        config_plugins.remove(plugin)
        bot.config.set_by_path(["plugins"], config_plugins)
        bot.config.save()
        lines.append('* **removed from config.json**')
    else:
        lines.append('* not in config.json')

    if len(lines) == 1:
        lines = ["no action was taken for {}".format(plugin.replace("_", "\\_"))]

    return "\n".join(lines)


@command.register(admin=True)
async def addplugin(bot, dummy, *args):
    """loads a plugin on the bot and adds it to the config, does not require
    plugins. prefix"""

    if not args:
        raise Help(_('plugin name is missing!'))
    plugin = args[0]

    config_plugins = bot.config.get_by_path(["plugins"]) or False
    if not isinstance(config_plugins, list):
        return _("this command only works with manually-configured plugins key "
                 "in config.json")

    lines = []
    loaded_plugins = plugins.get_configured_plugins(bot) or []
    all_plugins = plugins.retrieve_all_plugins(allow_underscore=True)

    plugin = _strip_plugin_path(plugin)

    if not plugin:
        return "invalid plugin name"

    if plugin not in all_plugins:
        return "plugin does not exist: {}".format(plugin.replace("_", "\\_"))

    lines.append("**add plugin: {}**".format(plugin.replace("_", "\\_")))

    if plugin in loaded_plugins:
        lines.append('* already loaded on bot start')
    else:
        module_path = "plugins.{}".format(plugin)
        escaped_module_path = module_path.replace("_", "\\_")
        try:
            if await plugins.load(bot, module_path):
                lines.append('* **loaded: {}**'.format(escaped_module_path))
            else:
                lines.append('* failed to load: {}'.format(escaped_module_path))
        except RuntimeError as err:
            lines.append(
                '* error loading {}: {}'.format(escaped_module_path, str(err)))

    if plugin in config_plugins:
        lines.append('* already in config.json')
    else:
        config_plugins.append(plugin)
        bot.config.set_by_path(["plugins"], config_plugins)
        bot.config.save()
        lines.append('* **added to config.json**')

    return "\n".join(lines)
