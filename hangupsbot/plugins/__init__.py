"""registration of plugin features"""

# TODO(das7pad): add the support for a plugin self unload function
# TODO(das7pad): add a context manager for the Tracker

import asyncio
import importlib
import inspect
import logging
import os
import sys

from hangupsbot import utils
from hangupsbot.base_models import BotMixin, TrackingMixin
from hangupsbot.commands import command
from hangupsbot.sinks import aiohttp_terminate


logger = logging.getLogger(__name__)


def recursive_tag_format(array, **kwargs):
    for index, tags in enumerate(array):
        if isinstance(tags, list):
            recursive_tag_format(tags, **kwargs)
        else:
            array[index] = array[index].format(**kwargs)


class AlreadyLoaded(utils.FormatBaseException):
    """Tried to load a plugin which is already loaded"""
    _template = 'Tried to load the plugin "%s" that is already loaded'


class NotLoaded(utils.FormatBaseException):
    """Tried to unload a plugin which is not loaded or already got unloaded"""
    _template = ('Tried to unload the plugin "%s" which is not loaded or '
                 'already got unloaded')


class Tracker(BotMixin):
    """used by the plugin loader to keep track of loaded commands
    designed to accommodate the dual command registration model (via function or
    decorator)
    """
    def __init__(self):
        self.list = {}
        self._current = {}
        self._running = False
        self.reset()
        TrackingMixin.set_tracking(self)

    async def clear(self):
        """clear all entrys"""
        self.reset()
        for plugin_data in self.list.values():
            for task in plugin_data["asyncio.task"]:
                task.cancel()
        self.list.clear()

    def reset(self):
        """clear the entries of the current plugin registration"""
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
            "asyncio.task": [],
            "aiohttp.web": [],
            "aiohttp.session": [],
        }

    async def start(self, metadata):
        """start gathering new plugin functionality, extend existing data

        Args:
            metadata (dict): required keys: 'module' and 'module.path'
        """
        waited = 0
        while self._running and waited < 100:
            await asyncio.sleep(0.1)
            waited += 1

        self.end() # cleanup from recent run
        self._running = True

        module_path = metadata['module.path']

        if module_path in self.list:
            # extend the last registration
            self._current = self.list[module_path]

        # overwrite the metadata for the current run
        self._current["metadata"] = metadata

    @property
    def current(self):
        """merge admin and user plugins and return the current registration

        Returns:
            dict: gathered data of the current plugin, see .reset() for details
        """
        self._current["commands"]["all"] = list(
            set(self._current["commands"]["admin"] +
                self._current["commands"]["user"]))
        return self._current

    def end(self):
        """save the current module data and register tagged commands"""
        current_module = self.current
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

                    # priories admin-linked tags if both exist
                    break

        self.reset() # remove current data from the registration
        self._running = False

    def register_command(self, type_, command_names, tags=None):
        """call during plugin init to register commands"""
        current_commands = self._current["commands"][type_]
        current_commands.extend([item.lower() for item in command_names])
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
        """add a tagged command to the plugin tracking"""
        commands_tagged = self._current["commands"]["tagged"]
        commands_tagged.setdefault(command_name, {})
        commands_tagged[command_name].setdefault(type_, set())

        tag_sets = set([frozenset(item if isinstance(item, list)
                                  else [item]) for item in tags])

        # registration might be called repeatedly,
        #  so only add the tag_sets if it doesnt exist
        if tag_sets > commands_tagged[command_name][type_]:
            commands_tagged[command_name][type_] |= tag_sets

        logger.debug("%s - [%s] tags: %s", command_name, type_, tags)

    def register_handler(self, function, pluggable, priority):
        """see module method"""
        self._current["handlers"].append((function, pluggable, priority))

    def register_shared(self, identifier, objectref):
        """track a registered shared

        Args:
            identifier (str): a unique identifier for the objectref
            objectref (mixed): the shared object
        """
        self._current["shared"].append((identifier, objectref))

    def register_aiohttp_web(self, group):
        """track the group(name) of an aiohttp listener"""
        if group not in self._current["aiohttp.web"]:
            self._current["aiohttp.web"].append(group)

    def register_asyncio_task(self, task):
        """add a single asyncio.Task to the plugin tracking"""
        self._current["asyncio.task"].append(task)

    def register_arg_preprocessor_group(self, name):
        """add a argument preprocessor to the plugin tracking"""
        if name not in self._current["commands"]["argument.preprocessors"]:
            self._current["commands"]["argument.preprocessors"].append(name)

    def register_aiohttp_session(self, session):
        """register a session that will be closed on plugin unload

        Args:
            session (aiohttp.ClientSession): a session to track
        """
        self._current["aiohttp.session"].append(session)


tracking = Tracker()                               # pylint:disable=invalid-name


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

    e.g. register_help('my text', name='my_cmd')
         register_help({'my_cmd': 'my text', 'my_second_cmd': 'other text'})

    Args:
        source (mixed): string or dict, a single text entry
            or multiple entries in a dict with command names as keys
        name (str): the command name of the single text

    Raises:
        ValueError: bad args, provide a dict with cmds or specify the cmd name
            for the single text
    """
    if isinstance(source, str) and name is not None:
        source = {name: source}
    elif not isinstance(source, dict):
        raise ValueError('check args')
    tracking.bot.memory.set_defaults(source, ['command_help'])

def register_handler(function, pluggable="message", priority=50):
    """register external message handler

    signature: function(bot, event, command)
               function(bot, event)
               function(bot)
               function()

    Args:
        function (callable): with signature: function(bot, event, command)
        pluggable (str): key in handler.EventHandler.pluggables, event type
        priority (int): change the sequence of handling the event
    """
    # pylint:disable=protected-access
    bot_handlers = tracking.bot._handlers
    # pylint:enable=protected-access
    bot_handlers.register_handler(function, pluggable, priority)

def register_sync_handler(function, name="message", priority=50):
    """register external sync handler

    signature: function(bot, event, command)
               function(bot, event)
               function(bot)
               function()

    Args:
        function (mixed): function or coroutine, see doc body for footprint
        name (str): key in bot.sync.pluggables, event type
        priority (int): change the sequence of handling the event, ignored
    """
    tracking.bot.sync.register_handler(function, name, priority)

def register_shared(identifier, objectref):
    """register a shared object to be called later

    Args:
        identifier (str): a unique identifier for the objectref
        objectref (mixed): the object to be shared

    Raises:
        RuntimeError: the identifier is already in use
    """
    tracking.bot.register_shared(identifier, objectref)

def start_asyncio_task(coro, *args, **kwargs):
    """start an async callable and track its execution

    Args:
        coro (coroutine): a coroutine function
        args (mixed): positional arguments for the function
        kwargs (mixed): keyword arguments for the function

    Returns:
        asyncio.Task: wrapper for the execution of the coroutine

    Raises:
        RuntimeError: the function is not a coroutine or coroutine function
    """
    loop = asyncio.get_event_loop()
    if asyncio.iscoroutinefunction(coro) or asyncio.iscoroutine(coro):
        expected = inspect.signature(coro).parameters
        if (expected and tuple(expected)[0] == 'bot'
                and tracking.bot not in args[:1]):
            args = (tracking.bot, ) + args
        task = asyncio.ensure_future(coro(*args, **kwargs),
                                     loop=loop)
    else:
        raise RuntimeError("coroutine function must be supplied")
    tracking.register_asyncio_task(task)
    logger.debug(task)
    return task

def register_commands_argument_preprocessor_group(name, preprocessors):
    # pylint:disable=invalid-name
    command.register_arg_preprocessor_group(name, preprocessors)

def register_aiohttp_session(session):
    """register a session that will be closed on plugin unload

    Args:
        session (aiohttp.ClientSession): a session to track
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
    * sub-plugin files (additional plugins inside a sub-folder) must be prefixed
        with the EXACT plugin/folder name for it to be retrieved, matching
        starting _ is optional if allow_underscore=True
    """

    if not plugin_path:
        plugin_path = os.path.dirname(__file__)

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
        bot (hangupsbot.HangupsBot): the running instance

    Returns:
        list[str]: a list of module paths
    """
    config_plugins = bot.config.get_option('plugins')

    if config_plugins is None: # must be unset in config or null
        logger.info("plugins is not defined, using ALL")
        plugin_list = retrieve_all_plugins()

    else:
        # perform fuzzy matching with actual retrieved plugins,
        # e.g. "abc" matches "xyz.abc"
        # if more than one match found, don't load plugin
        plugins_included = []
        plugins_excluded = retrieve_all_plugins(allow_underscore=True)

        plugin_name_ambiguous = []
        plugin_name_not_found = []

        for item_no, configured in enumerate(config_plugins):
            dot_configured = "." + configured

            matches = []
            for found in plugins_excluded:
                full_path = "hangupsbot.plugins." + found
                if full_path.endswith(dot_configured):
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
        bot (hangupsbot.HangupsBot): the running instance

    Raises:
        CancelledError: shutdown in progress
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
        bot (hangupsbot.HangupsBot): the running instance
    """
    all_plugins = tracking.list.copy()
    done = await asyncio.gather(*[unload(bot, module_path)
                                  for module_path in all_plugins],
                                return_exceptions=True)

    for module in all_plugins:
        result = done.pop(0)
        if isinstance(result, NotLoaded):
            logger.info(repr(result))
            continue
        if not isinstance(result, Exception):
            continue
        logger.error('`unload("%s")` failed with Exception %s',
                     module, repr(result))

async def load(bot, module_path, module_name=None):
    """loads a single plugin-like object as identified by module_path

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        module_path (str): python import style relative to the main script
        module_name (str): custom name

    Returns:
        bool: True if the plugin was loaded successfully

    Raises:
        AlreadyLoaded: the plugin is already loaded
    """
    if module_path in tracking.list:
        raise AlreadyLoaded(module_path)

    module_name = module_name or module_path.split(".")[-1]

    await tracking.start({"module": module_name, "module.path": module_path})

    if not load_module(module_path):
        tracking.end()
        await unload(bot, module_path)
        return False

    real_module_path = 'hangupsbot.' + module_path
    setattr(sys.modules[real_module_path], 'print', utils.print_to_logger)
    if hasattr(sys.modules[real_module_path], "hangups_shim"):
        logger.info("%s has legacy hangups reference", module_name)

    public_functions = list(
        inspect.getmembers(sys.modules[real_module_path], inspect.isfunction))

    candidate_commands = []

    # gather functions and run optional callable _initialise or _initialize
    try:
        for function_name, the_function in public_functions:
            if function_name not in ("_initialise", "_initialize"):
                if not function_name.startswith("_"):
                    # skip private functions
                    candidate_commands.append(
                        (function_name.lower(), the_function))
                continue

            # accepted function signatures:
            # coroutine/function()
            # coroutine/function(bot) - parameter must be named "bot"
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
        tracking.end()
        await unload(bot, module_path)
        return False

    # register filtered functions
    # tracking.current and the CommandDispatcher might be out of sync if a
    #  combination of decorators and register_{admin, user}_command
    #  is used since decorators execute immediately upon import
    plugin_tracking = tracking.current

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

    logger.debug("%s - %s", module_name,
                 ", ".join(registered_commands) or "no commands")

    tracking.end()
    return True

def load_module(module_path):
    """(re) load an external module

    Args:
        module_path (str): the path to the module relative to the main script

    Returns:
        bool: True if no Exception was raised on (re)load, otherwise False
    """
    message = "search for plugin in sys.modules"
    module_path = 'hangupsbot.' + module_path
    try:
        if module_path in sys.modules:
            message = "reload"
            importlib.reload(sys.modules[module_path])

        else:
            message = "import"
            importlib.import_module(module_path)

        return True
    except:             # capture all Exceptions   # pylint: disable=bare-except
        logger.exception("load_module %s: %s", module_path, message)
        return False

async def unload(bot, module_path):
    """unload a plugin including all external registered resources

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        module_path (str): plugin path on disk relative to the main script

    Returns:
        bool: True if the plugin was fully unloaded

    Raises:
        NotLoaded: the plugin was not loaded or is already unloaded
    """
    try:
        plugin = tracking.list.pop(module_path)
    except KeyError:
        logger.debug('Duplicate call on `plugins.unload(bot, "%s")`',
                     module_path)
        raise NotLoaded(module_path) from None

    for command_name in plugin["commands"]["all"]:
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

    # pylint:disable=protected-access
    bot._handlers.deregister_plugin(module_path)
    # pylint:enable=protected-access
    bot.sync.deregister_plugin(module_path)

    shared = plugin["shared"]
    for shared_def in shared:
        identifier = shared_def[0]
        if identifier in bot.shared:
            logger.debug("removing shared %s", identifier)
            del bot.shared[identifier]

    for task in plugin["asyncio.task"]:
        logger.debug("cancelling task: %s", task)
        task.cancel()

    # wait for the completion of all task
    try:
        done = await asyncio.wait_for(asyncio.gather(*plugin["asyncio.task"],
                                                     return_exceptions=True), 5)
        failed = []
        for task in plugin["asyncio.task"]:
            result = done.pop(0)
            if not isinstance(result, Exception):
                continue
            failed.append("%s\nexited with Exception %s" % (task, repr(result)))

        if failed:
            logger.info("not all tasks of %s were shutdown gracefully:\n%s",
                        module_path, "\n".join(failed))
    except TimeoutError:
        logger.info("not all tasks of %s were shutdown gracefully after 5sec",
                    module_path)

    if plugin["aiohttp.web"]:
        for group in plugin["aiohttp.web"]:
            await aiohttp_terminate(group)

    for groupname in plugin["commands"]["argument.preprocessors"]:
        command.arguments_parser.deregister_preprocessor_group(groupname)

    for session in plugin['aiohttp.session']:
        session.close()

    logger.debug("%s unloaded", module_path)
    return True

SENTINELS = {}

async def reload_plugin(bot, module_path):
    """reload a plugin and keep track of multiple reloads

    Note: the plugin may reset the sentinel on a successful internal load

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        module_path (str): plugin path on disk relative to the main script

    Returns:
        bool: False if the plugin may not be reloaded again, otherwise True
    """
    if module_path in tracking.list:
        await unload(bot, module_path)

    repeat = SENTINELS.setdefault(module_path, 0)
    if repeat >= 3:
        logger.critical('too many reloads of %s, enter fail state', module_path)
        return False
    SENTINELS[module_path] += 1
    await load(bot, module_path)
    return True
