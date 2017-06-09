"""registration of plugin features"""

#TODO(das7pad): add the support for a plugin selfunload function

import asyncio
import importlib
import inspect
import logging
import os
import sys

from inspect import getmembers, isfunction

import hangups_shim
from commands import command
import utils


logger = logging.getLogger(__name__)


def recursive_tag_format(array, **kwargs):
    for index, tags in enumerate(array):
        if isinstance(tags, list):
            recursive_tag_format(tags, **kwargs)
        else:
            array[index] = array[index].format(**kwargs)

class tracker:
    """used by the plugin loader to keep track of loaded commands
    designed to accommodate the dual command registration model (via function or
    decorator)
    """
    def __init__(self):
        self.bot = None
        self.list = {}
        self._current = {}
        self._running = False
        self.reset()

    def set_bot(self, bot):
        self.bot = bot

    def reset(self):
        self._current = {
            "commands": {
                "admin": [],
                "user": [],
                "all": None,
                "tagged": {},
                "tagged_registered": [],
                "argument.preprocessors": [],
            },
            "handlers": [],
            "shared": [],
            "metadata": {},
            "threads": [],
            "asyncio.task": [],
            "aiohttp.web": [],
            "aiohttp.session": [],
        }

    async def start(self, metadata):
        """start gathering new plugin functionality, extend existing data

        Args:
            metadata: dict, required keys: 'module' and 'module.path'
        """
        waited = 0
        while self._running and waited < 100:
            await asyncio.sleep(0.1)
        self._running = True

        self.end() # cleanup from recent run

        module_path = metadata['module.path']

        if module_path in self.list:
            # extend the last registration
            self._current = self.list[module_path]

        # overwrite the metadata for the current run
        self._current["metadata"] = metadata

    def current(self):
        self._current["commands"]["all"] = list(
            set(self._current["commands"]["admin"] +
                self._current["commands"]["user"]))
        return self._current

    def end(self):
        """save the current module data and register tagged commands"""
        current_module = self.current()
        if not current_module['metadata']:
            # empty plugin data, last run is already finished
            return

        self.list[current_module["metadata"]["module.path"]] = current_module

        # sync tagged commands to the command dispatcher
        for command_, type_tags in current_module["commands"]["tagged"].items():
            if command_ in current_module['commands']['tagged_registered']:
                continue
            for type_ in ["admin", "user"]:
                if type_ in type_tags:
                    command.register_tags(command_, type_tags[type_])
                    current_module['commands']['tagged_registered'].append(
                        command_)

                    # prioritse admin-linked tags if both exist
                    break

        self.reset() # remove current data from the registration
        self._running = False

    def register_command(self, type_, command_names, tags=None):
        """call during plugin init to register commands"""
        current_commands = self._current["commands"][type_]
        current_commands.extend(command_names)
        self._current["commands"][type_] = list(set(current_commands))

        user_setting = self.bot.config.get_option('plugins.tags.auto-register')
        if user_setting is None:
            user_setting = True

        if not tags and not user_setting:
            return

        if not tags:
            # assumes config["plugins.tags.auto-register"] == True
            tags = []

        elif isinstance(tags, str):
            tags = [tags]

        if user_setting is True:
            presets = ["{plugin}-{command}", "{plugin}-{type}"]

        elif user_setting:
            presets = ([user_setting] if isinstance(user_setting, str)
                       else user_setting)

        else:
            presets = []

        for command_name in command_names:
            command_tags = list(tags) + list(presets) # use copies

            recursive_tag_format(command_tags,
                                 command=command_name,
                                 type=type_,
                                 plugin=self._current["metadata"]["module"])

            self.register_tags(type_, command_name, command_tags)

    def register_tags(self, type_, command_name, tags):
        commands_tagged = self._current["commands"]["tagged"]
        commands_tagged.setdefault(command_name, {})
        commands_tagged[command_name].setdefault(type_, set())

        tagsets = set([frozenset(item if isinstance(item, list)
                                 else [item]) for item in tags])

        # registration might be called repeatedly,
        #  so only add the tagsets if it doesnt exist
        if tagsets > commands_tagged[command_name][type_]:
            commands_tagged[command_name][type_] |= tagsets

        logger.debug("%s - [%s] tags: %s", command_name, type_, tags)

    def register_handler(self, function, type_, priority):
        self._current["handlers"].append((function, type_, priority))

    def register_shared(self, identifier, objectref):
        """track a registered shared

        Args:
            identifier: string, a unique identifier for the objectref
            objectref: any type, the shared object
        """
        self._current["shared"].append((identifier, objectref))

    def register_thread(self, thread):
        self._current["threads"].append(thread)

    def register_aiohttp_web(self, group):
        """track the group(name) of an aiohttp listener"""
        if group not in self._current["aiohttp.web"]:
            self._current["aiohttp.web"].append(group)

    def register_asyncio_task(self, task):
        self._current["asyncio.task"].append(task)

    def register_command_argument_preprocessors_group(self, name):
        if name not in self._current["commands"]["argument.preprocessors"]:
            self._current["commands"]["argument.preprocessors"].append(name)

    def register_aiohttp_session(self, session):
        """register a session that will be closed on pluginunload

        Args:
            session: aio.client.ClientSession-like instance
        """
        self._current["aiohttp.session"].append(session)


tracking = tracker()


# helpers, used by loaded plugins to register commands

def register_user_command(command_names, tags=None):
    """user command registration"""
    if not isinstance(command_names, list):
        command_names = [command_names]
    tracking.register_command("user", command_names, tags=tags)

def register_admin_command(command_names, tags=None):
    """admin command registration, overrides user command registration"""
    if not isinstance(command_names, list):
        command_names = [command_names]
    tracking.register_command("admin", command_names, tags=tags)

def register_help(source, name=None):
    """help content registration

    Args:
        source: string or dict, a single text or multiple in a dict with command
            names as keys
        name: string, the command name of the single text

    Raises:
        ValueError: bad args, provide a dict with cmds or specify the cmd name
            for the single text
    """
    if isinstance(source, str) and name is not None:
        source = {name: source}
    elif not isinstance(source, dict):
        raise ValueError('check args')
    tracking.bot.memory.set_defaults(source, ['command_help'])

def register_handler(function, type="message", priority=50):
    """register external handler"""
    bot_handlers = tracking.bot._handlers
    bot_handlers.register_handler(function, type, priority)

def register_shared(identifier, objectref):
    """register a shared object to be called later

    Args:
        identifier: string, a unique identifier for the objectref
        objectref: any type, the object to be shared

    Raises:
        RuntimeError: the identifier is already in use
    """
    tracking.bot.register_shared(identifier, objectref)

def start_asyncio_task(function, *args, **kwargs):
    """start an async callable and track its execution

    Args:
        function: callable, async coroutine or coroutine_function
        args: tuple, positional arguments for the function
        kwargs: dict, keyword arguments for the function

    Returns:
        asyncio.Task instance for the execution of the function

    Raises:
        RuntimeError: the function is not a coroutine or coroutine_function
    """
    loop = asyncio.get_event_loop()
    if asyncio.iscoroutinefunction(function):
        task = asyncio.ensure_future(function(tracking.bot, *args, **kwargs),
                                     loop=loop)
    elif asyncio.iscoroutine(function):
        task = asyncio.ensure_future(function(),
                                     loop=loop)
    else:
        raise RuntimeError("coroutine function must be supplied")
    tracking.register_asyncio_task(task)
    logger.debug(task)
    return task

def register_commands_argument_preprocessor_group(name, preprocessors):
    command.register_argument_preprocessor_group(name, preprocessors)

def register_aiohttp_session(session):
    """register a session that will be closed on pluginunload

    Args:
        session: aio.client.ClientSession-like instance
    """
    tracking.register_aiohttp_session(session)

# plugin loader

def retrieve_all_plugins(plugin_path=None, must_start_with=None,
                         allow_underscore=False):
    """recursively loads all plugins from the standard plugins path

    * plugin file/folder name starting with:
        . or __ will be ignored unconditionally
        _ will be ignored, unless allow_underscore=True
    * folders containing plugins must have at least an empty __init__.py file
    * sub-plugin files (additional plugins inside a subfolder) must be prefixed
        with the EXACT plugin/folder name for it to be retrieved, matching
        starting _ is optional if allow_underscore=True
    """

    if not plugin_path:
        plugin_path = "{path}{separator}plugins".format(
            path=os.path.dirname(os.path.realpath(sys.argv[0])),
            separator=os.sep)

    plugin_list = []

    nodes = os.listdir(plugin_path)

    for node_name in nodes:
        full_path = os.path.join(plugin_path, node_name)

        # node_name without .py extension
        module_names = [os.path.splitext(node_name)[0]]

        if (node_name.startswith(("__", ".")) or
                node_name.startswith("_") and not allow_underscore):
            continue

        if must_start_with is not None:
            prefixes = [must_start_with]
            if allow_underscore:
                # allow: X/_X_Y _X/X_Y _X/_X_Y
                # underscore optional when checking sub-plugin visibility
                if must_start_with.startswith('_'):
                    prefixes.append(must_start_with[1:])
                else:
                    prefixes.append('_' + must_start_with)
            if not node_name.startswith(tuple(prefixes)):
                continue

        if not os.path.isfile(full_path):
            if not os.path.isfile(os.path.join(full_path, "__init__.py")):
                continue

            submodules = retrieve_all_plugins(full_path,
                                              must_start_with=node_name,
                                              allow_underscore=allow_underscore)
            for submodule in submodules:
                module_names.append(module_names[0] + "." + submodule)

        elif not node_name.endswith(".py"):
            continue

        plugin_list.extend(module_names)

    logger.debug("retrieved %s: %s.%s", len(plugin_list),
                 must_start_with or "plugins", plugin_list)
    return plugin_list


def get_configured_plugins(bot):
    """get the configured and also available plugins to load

    Args:
        bot: HangupsBot instance

    Returns:
        list of strings, a list of module paths
    """
    config_plugins = bot.config.get_option('plugins')

    if config_plugins is None: # must be unset in config or null
        logger.info("plugins is not defined, using ALL")
        plugin_list = retrieve_all_plugins()

    else:
        """
        perform fuzzy matching with actual retrieved plugins,
        e.g. "abc" matches "xyz.abc"
        if more than one match found, don't load plugin
        """
        plugins_included = []
        plugins_excluded = retrieve_all_plugins(allow_underscore=True)

        plugin_name_ambiguous = []
        plugin_name_not_found = []

        for item_no, configured in enumerate(config_plugins):
            dotconfigured = "." + configured

            matches = []
            for found in plugins_excluded:
                fullfound = "plugins." + found
                if fullfound.endswith(dotconfigured):
                    matches.append(found)
            num_matches = len(matches)

            if num_matches <= 0:
                logger.debug("%s:%s no match", item_no, configured)
                plugin_name_not_found.append([item_no, configured])

            elif num_matches == 1:
                logger.debug("%s:%s matched to %s",
                             item_no, configured, matches[0])
                plugins_included.append(matches[0])
                plugins_excluded.remove(matches[0])

            else:
                logger.debug("%s:%s ambiguous, matches %s",
                             item_no, configured, matches)
                plugin_name_ambiguous.append([item_no, configured])

        if plugins_excluded:
            # show plugins visible to the loader, but not actually loaded
            logger.info("excluded %s: %s",
                        len(plugins_excluded), plugins_excluded)

        if plugin_name_ambiguous:
            # include the index of item(s) in the plugins config key
            logger.warning("ambiguous: %s",
                           ["{}:{}".format(_num, _name)
                            for _num, _name in plugin_name_ambiguous])

        if plugin_name_not_found:
            # include the index of item(s) in the plugins config key
            logger.warning("not found: %s",
                           ["{}:{}".format(_num, _name)
                            for _num, _name in plugin_name_not_found])

        plugin_list = plugins_included

    logger.debug("included %s: %s", len(plugin_list), plugin_list)
    return plugin_list

async def load_user_plugins(bot):
    """loads all user plugins

    Args:
        bot: HangupsBot instance
    """
    plugin_list = get_configured_plugins(bot)

    for module in plugin_list:
        module_path = "plugins.{}".format(module)
        try:
            await load(bot, module_path)
        except asyncio.CancelledError:
            raise
        except:         # capture all Exceptions   # pylint: disable=bare-except
            logger.exception(module_path)

async def unload_all(bot):
    """unload user plugins

    Args:
        bot: HangupsBot instance
    """
    for module_path in tracking.list.copy():
        try:
            await unload(bot, module_path)

        except RuntimeError:
            logger.exception("%s could not be unloaded", module_path)

async def load(bot, module_path, module_name=None):
    """loads a single plugin-like object as identified by module_path

    Args:
        bot: HangupsBot instance
        module_path: string, python import style relative to the main script
        module_name: string, custom name

    Returns:
        boolean, True if the plugin was loaded successfully
    """
    module_name = module_name or module_path.split(".")[-1]

    if module_path in tracking.list:
        raise RuntimeError("{} already loaded".format(module_path))

    await tracking.start({"module": module_name, "module.path": module_path})

    if not load_module(module_path):
        return False

    setattr(sys.modules[module_path], 'print', utils.print_to_logger)
    if hasattr(sys.modules[module_path], "hangups"):
        logger.debug("%s has legacy hangups reference", module_name)
        setattr(sys.modules[module_path], "hangups", hangups_shim)

    public_functions = list(getmembers(sys.modules[module_path], isfunction))

    candidate_commands = []

    # run optional callable _initialise or _initialize and cature
    try:
        for function_name, the_function in public_functions:
            if function_name not in ("_initialise", "_initialize"):
                if not function_name.startswith("_"):
                    # skip private functions
                    candidate_commands.append((function_name, the_function))
                continue

            # accepted function signatures:
            # coro/function()
            # coro/function(bot) - parameter must be named "bot"
            expected = list(inspect.signature(the_function).parameters)
            if len(expected) > 1 or (expected and expected[0] != "bot"):
                # plugin not updated since v2.4
                logger.warning("%s of %s does not comply with the current "
                               "initialize standard!",
                               function_name, module_path)
                continue

            result = the_function(bot) if expected else the_function()
            if asyncio.iscoroutinefunction(the_function):
                await result

    except:             # capture all Exceptions   # pylint: disable=bare-except
        logger.exception("error on plugin init: %s", module_path)
        return False

    """
    register filtered functions
    tracking.current() and the CommandDispatcher might be out of sync if a
     combination of decorators and register_user_command/register_admin_command
     is used since decorators execute immediately upon import
    """
    plugin_tracking = tracking.current()

    explicit_admin_commands = plugin_tracking["commands"]["admin"]
    all_commands = plugin_tracking["commands"]["all"]
    registered_commands = []

    for function_name, the_function in candidate_commands:
        if function_name not in all_commands:
            continue

        is_admin = False
        text_function_name = function_name
        if function_name in explicit_admin_commands:
            is_admin = True
            text_function_name = "*" + text_function_name

        command.register(the_function, admin=is_admin, final=True)

        registered_commands.append(text_function_name)

    if registered_commands:
        logger.debug("%s - %s", module_name, ", ".join(registered_commands))
    else:
        logger.debug("%s - no commands", module_name)

    tracking.end()
    return True

def load_module(module_path):
    """(re) load an external module

    Args:
        module_path: string, the path to the module relative to the main script

    Returns:
        boolean, True if no Exception was raised on (re)load, otherwise False
    """
    message = "search for plugin in sys.modules"
    try:
        if module_path in sys.modules:
            message = "reload"
            importlib.reload(sys.modules[module_path])

        else:
            message = "import"
            importlib.import_module(module_path)

        return True
    except:
        logger.exception("load_module %s: %s", module_path, message)
        return False

async def unload(bot, module_path):
    plugin = tracking.list.pop(module_path)

    if len(plugin["threads"]) != 0:
        raise RuntimeError("%s has %s thread(s)" % (module_path,
                                                    len(plugin["threads"])))

    loop = asyncio.get_event_loop()
    all_commands = plugin["commands"]["all"]
    for command_name in all_commands:
        if command_name in command.commands:
            logger.debug("removing function %s", command_name)
            del command.commands[command_name]
        if command_name in command.admin_commands:
            logger.debug("deregistering admin command %s", command_name)
            command.admin_commands.remove(command_name)

    for type_ in plugin["commands"]["tagged"]:
        for command_name in plugin["commands"]["tagged"][type_]:
            if command_name in command.command_tagsets:
                logger.debug("deregistering tagged command %s", command_name)
                del command.command_tagsets[command_name]

    for type_ in bot._handlers.pluggables:
        for handler in bot._handlers.pluggables[type_]:
            if handler[2]["module.path"] == module_path:
                logger.debug("removing handler %s %s", type_, handler)
                bot._handlers.pluggables[type_].remove(handler)

    shared = plugin["shared"]
    for shared_def in shared:
        identifier = shared_def[0]
        if identifier in bot.shared:
            logger.debug("removing shared %s", identifier)
            del bot.shared[identifier]

    for task in plugin["asyncio.task"]:
        logger.debug("cancelling task: %s", task)
        loop.call_soon_threadsafe(task.cancel)
        # await for the execution
        await asyncio.sleep(0)

    if len(plugin["aiohttp.web"]) > 0:
        from sinks import aiohttp_terminate # XXX: needs to be late-imported
        for group in plugin["aiohttp.web"]:
            await aiohttp_terminate(group)

    for groupname in plugin["commands"]["argument.preprocessors"]:
        del command.preprocessors[groupname]

    for session in plugin['aiohttp.session']:
        session.close()

    logger.debug("%s unloaded", module_path)
    return True

SENTINALS = {}

async def reload_plugin(bot, module_path):
    """reload a plugin and keep track of multiple reloads

    Note: the plugin may reset the sentinal on a successfull internal load

    Args:
        module_path: string, plugin path on disk relative to the main script

    Returns:
        boolean, False if the plugin may not be reloaded again, otherwise True
    """
    repeat = SENTINALS.setdefault(module_path, 0)
    if repeat >= 3:
        logger.warning('too many reloads of %s, enter failstate', module_path)
        return False
    SENTINALS[module_path] += 1
    await unload(bot, module_path)
    await load(bot, module_path)
    return True
