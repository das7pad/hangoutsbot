"""command dispatch for the HangupsBot"""
#TODO(das7pad) move args parser to own module
#TODO(das7pad) refactor .get_available_commands()
#TODO(das7pad) extract config entrys to defaults
import asyncio
import logging
import re
import time

import hangups

import plugins

logger = logging.getLogger(__name__)

class Help(Exception):
    """raise to request the help entry of the current command

    opt: supplied text as string in the arguments will be prepended to the help
    """
    pass

class CommandDispatcher(object):
    """Register commands and run them"""
    def __init__(self):
        self.bot = None
        self.commands = {}
        self.admin_commands = []
        self.unknown_command = None
        self.blocked_command = None
        self.tracking = None

        self.command_tagsets = {}

        """
        inbuilt argument preprocessors, recognises:
        * one_chat_id (also resolves #conv)
          * @user
          * #conv|@user (tagset convuser format)
          * abcd|@user (tagset convuser format)
        * one_conv_id
          * #conv
          * #conv|* (tagset convuser format)
          * #conv|123 (tagset convuser format)
        * test cases that won't match:
          * #abcd#
          * ##abcd
          * ##abcd##
          * ##abcd|*
          * @user|abcd
          * wxyz@user
          * @user@wxyz
        """

        self.preprocessors = {"inbuilt": {
            r"^(#?[\w|]+[^#]\|)?@[\w]+[^@]$": self.one_chat_id,
            r"^#[\w|]+[^#]$": self.one_conv_id}}

    def one_chat_id(self, token, internal_context, all_users=False):
        subtokens = token.split("|", 1)

        if subtokens[0].startswith("#"):
            # probably convuser format - resolve conversation id first
            subtokens[0] = self.one_conv_id(subtokens[0], internal_context)

        text = subtokens[-1][1:]

        if text == "me":
            # current user chat_id
            subtokens[-1] = internal_context.user.id_.chat_id
        else:
            user_memory = self.bot.memory["user_data"]
            chat_ids = (list(self.bot.conversations[internal_context.conv_id]
                             ["participants"])
                        if all_users else list(user_memory.keys()))

            matched_users = {}
            for chat_id in chat_ids:
                user_data = user_memory[chat_id]
                nickname_lower = (user_data["nickname"].lower()
                                  if "nickname" in user_data else "")
                fullname_lower = user_data["_hangups"]["full_name"].lower()

                if text == nickname_lower:
                    matched_users[chat_id] = chat_id
                    break

                elif (text in fullname_lower or
                      text in fullname_lower.replace(" ", "")):
                    matched_users[chat_id] = chat_id

            if len(matched_users) == 1:
                subtokens[-1] = list(matched_users)[0]
            elif not matched_users:
                if internal_context:
                    # redo the user search, expanded to all users
                    # since this is calling itself again,
                    # completely overwrite subtokens
                    subtokens = self.one_chat_id(
                        token,
                        internal_context,
                        all_users=True).split("|", 1)
                else:
                    raise ValueError("{} returned no users".format(token))
            else:
                raise ValueError("{} returned more than one user".format(token))

        return "|".join(subtokens)

    def one_conv_id(self, token, internal_context):
        subtokens = token.split("|", 1)

        text = subtokens[0][1:]
        if text == "here":
            # current conversation id
            subtokens[0] = internal_context.conv_id
        else:
            filter_ = "(type:GROUP)and(text:{})".format(text)
            conv_list = self.bot.conversations.get(filter_)
            if len(conv_list) == 1:
                subtokens[0] = next(iter(conv_list))
            elif not conv_list:
                raise ValueError("{} returned no conversations".format(token))
            else:
                raise ValueError("{} returned too many conversations".format(
                    token))

        return "|".join(subtokens)

    def preprocess_arguments(self, args, internal_context, force_trigger="",
                             force_groups=[]):
        """custom preprocessing for use by other plugins, specify:
        * force_trigger word to override config, default
          prevents confusion if botmin has overridden this for their own usage
        * force_groups to a list of resolver group names
          at least 1 must exist, otherwise all resolvers will be used (as usual)
        """
        all_groups = list(self.preprocessors.keys())
        force_groups = [g for g in force_groups if g in all_groups]
        all_groups = force_groups or all_groups

        _implicit = (bool(force_groups)
                     or not self.bot.config.get_option(
                         "commands.preprocessor.explicit"))
        _trigger = (force_trigger
                    or self.bot.config.get_option(
                        "commands.preprocessor.trigger")
                    or "resolve").lower()

        _trigger_on = "+" + _trigger
        _trigger_off = "-" + _trigger
        _separator = ":"

        """
        simple finite state machine parser:

        * arguments are processed in order of input, from left-to-right
        * default setting is always post-process
          * switch off with config.json: commands.preprocessor.explicit = true
        * default base trigger keyword = "resolve"
          * override with config.json: commands.preprocessor.trigger
          * full trigger keywords are:
            * +<trigger> (add)
            * -<trigger> (remove)
          * customised trigger word must be unique enough to prevent conflicts for other plugin parameters
          * all examples here assume the trigger keyword is the default
          * devs: if conflict arises, other plugins have higher priority than this
        * activate all resolvers for subsequent keywords (not required if implicit):
            +resolve
        * deactivate all resolvers for subsequent keywords:
            -resolve
        * activate specific resolver groups via keyword:
            +resolve:<comma-separated list of resolver groups, no spaces> e.g.
            +resolve:inbuilt,customalias1,customalias2
        * deactivate all active resolvers via keyword:
            +resolve:off
            +resolve:false
            +resolve:0
        * deactivate specific resolvers via keyword:
            -resolve:inbuilt
            -resolve:inbuilt,customa
        * escape trigger keyword with:
          * quotes
              "+resolve"
          * backslash
              \+resolve
        """

        if "inbuilt" in all_groups:
            # lowest priority: inbuilt
            all_groups.remove("inbuilt")
            all_groups.append("inbuilt")

        if _implicit:
            # always-on
            default_groups = all_groups
        else:
            # on-demand
            default_groups = []

        apply_resolvers = default_groups
        new_args = []
        for arg in args:
            arg_lower = arg.lower()
            skip_arg = False
            if _trigger_on == arg_lower:
                # explicitly turn on all resolvers
                #   +resolve
                apply_resolvers = all_groups
                skip_arg = True
            elif _trigger_off == arg_lower:
                # explicitly turn off all resolvers
                #   -resolve
                apply_resolvers = []
                skip_arg = True
            elif arg_lower.startswith(_trigger_on + _separator):
                _right = arg_lower.split(_separator, 1)[-1]
                if not _right or _right in ("off", "false", "0"):
                    # turn off all resolver groups
                    #   +resolve:off
                    #   +resolve:false
                    #   +resolve:0
                    #   +resolve:
                    apply_resolvers = []
                elif _right == "*":
                    # turn on all resolver groups
                    #   +resolve:*
                    apply_resolvers = all_groups
                else:
                    # turn on specific resolver groups
                    #   +resolve:inbuilt
                    #   +resolve:inbuilt,customa,customb
                    apply_resolvers = _right.split(",")
                skip_arg = True
            elif arg_lower.startswith(_trigger_off + _separator):
                _right = arg_lower.split(_separator, 1)[-1]
                if not _right or _right in "*":
                    # turn off all resolver groups
                    #   -resolve:*
                    #   -resolve:
                    apply_resolvers = []
                else:
                    # turn off specific groups:
                    #   -resolve:inbuilt
                    #   -resolve:customa,customb
                    for _group in _right.split(","):
                        apply_resolvers.remove(_group)
                skip_arg = True
            if skip_arg:
                # never consume the trigger term
                continue
            for rname in [rname
                          for rname in apply_resolvers
                          if rname in all_groups]:
                for pattern, callee in self.preprocessors[rname].items():
                    if re.match(pattern, arg, flags=re.IGNORECASE):
                        _arg = callee(arg, internal_context)
                        if _arg:
                            arg = _arg
                            continue
            new_args.append(arg)

        return new_args

    def set_bot(self, bot):
        """extended init

        Args:
            bot: HangupsBot instance
        """
        self.bot = bot
        # set the default timeout for commands to execute to 5minutes
        bot.config.set_defaults({'command_timeout': 5*60})

    def set_tracking(self, tracking):
        """register the plugin tracking for commands

        Args:
            tracking: plugins.Tracker instance
        """
        self.tracking = tracking

    def register_tags(self, command, tagsets):
        if command not in self.command_tagsets:
            self.command_tagsets[command] = set()

        if isinstance(tagsets, str):
            tagsets = set([tagsets])

        self.command_tagsets[command] = self.command_tagsets[command] | tagsets

    @property
    def deny_prefix(self):
        config_tags_deny_prefix = self.bot.config.get_option(
            'commands.tags.deny-prefix') or "!"
        return config_tags_deny_prefix

    @property
    def escalate_tagged(self):
        config_tags_escalate = self.bot.config.get_option(
            'commands.tags.escalate') or False
        return config_tags_escalate

    def get_available_commands(self, bot, chat_id, conv_id):
        start_time = time.time()

        config_tags_deny_prefix = self.deny_prefix
        config_tags_escalate = self.escalate_tagged

        config_admins = bot.get_config_suboption(conv_id, 'admins')
        is_admin = False
        if chat_id in config_admins:
            is_admin = True

        commands_admin = bot.get_config_suboption(conv_id, 'commands_admin') or []
        commands_user = bot.get_config_suboption(conv_id, 'commands_user') or []
        commands_tagged = bot.get_config_suboption(conv_id, 'commands_tagged') or {}

        # convert commands_tagged tag list into a set of (frozen)sets
        commands_tagged = { key: set([ frozenset(value if isinstance(value, list) else [value])
            for value in values ]) for key, values in commands_tagged.items() }
        # combine any plugin-determined tags with the config.json defined ones
        if self.command_tagsets:
            for command, tagsets in self.command_tagsets.items():
                if command not in commands_tagged:
                    commands_tagged[command] = set()
                commands_tagged[command] = commands_tagged[command] | tagsets

        all_commands = set(self.commands)

        admin_commands = set()
        user_commands = set()

        if commands_admin is True:
            """commands_admin: true # all commands are admin-only"""
            admin_commands = all_commands

        elif commands_user is True:
            """commands_user: true # all commands are user-only"""
            user_commands = all_commands

        elif commands_user:
            """commands_user: [ "command", ... ] # listed are user commands, others admin-only"""
            user_commands = set(commands_user)
            admin_commands = all_commands - user_commands

        else:
            """default: follow config["commands_admin"] + plugin settings"""
            admin_commands = set(commands_admin) | set(self.admin_commands)
            user_commands = all_commands - admin_commands

        # make admin commands unavailable to non-admin user
        if not is_admin:
            admin_commands = set()

        if commands_tagged:
            _set_user_tags = set(bot.tags.useractive(chat_id, conv_id))

            for command, tags in commands_tagged.items():
                if command not in all_commands:
                    # optimisation: don't check commands that aren't loaded into framework
                    continue

                # raise tagged command access level if escalation required
                if config_tags_escalate and command in user_commands:
                    user_commands.remove(command)

                # is tagged command generally available (in user_commands)?
                # admins always get access, other users need appropriate tag(s)
                # XXX: optimisation: check admin_commands to avoid unnecessary scanning
                if command not in user_commands|admin_commands:
                    for _match in tags:
                        _set_allow = set([_match] if isinstance(_match, str) else _match)
                        if is_admin or _set_allow <= _set_user_tags:
                            admin_commands.update([command])
                            break

            if not is_admin:
                # tagged commands can be explicitly denied
                _denied = set()
                for command in user_commands|admin_commands:
                    if command in commands_tagged:
                        tags = commands_tagged[command]
                        for _match in tags:
                            _set_allow = set([_match] if isinstance(_match, str) else _match)
                            _set_deny = { config_tags_deny_prefix + x for x in _set_allow }
                            if _set_deny <= _set_user_tags:
                                _denied.update([command])
                                break
                admin_commands = admin_commands - _denied
                user_commands = user_commands - _denied

        user_commands = user_commands - admin_commands # ensure no overlap

        interval = time.time() - start_time
        logger.debug("get_available_commands() - {}".format(interval))

        return {"admin": list(admin_commands), "user": list(user_commands)}

    async def run(self, bot, event, *args, **kwds):
        """Run a command

        Args:
            bot: HangupsBot instance
            event: event.ConversationEvent like instance
            args: tuple of string, including the command name in fist place
            kwds: dict, additional info to the execution including the key
                'raise_exceptions' to raise them instead of sending a message
        """
        command_name = args[0].lower()
        func = self.commands.get(command_name, self.unknown_command)
        if func is None:
            raise KeyError("command {} not found".format(command_name))

        """default: if exceptions occur in a command, output as message
        supply keyword argument raise_exceptions=True to override behaviour"""
        raise_exceptions = kwds.pop("raise_exceptions", False)

        setattr(event, 'command_name', command_name)

        conv_id = event.conv_id
        context = None
        try:
            coro = (func if asyncio.iscoroutinefunction(func)
                    else asyncio.coroutine(func))
            result = await asyncio.wait_for(coro(bot, event, *args[1:], **kwds),
                                            bot.config['command_timeout'])

        except asyncio.CancelledError:
            # shutdown in progress
            raise

        except asyncio.TimeoutError:
            text = _('command execution of "{}" timed out').format(command_name)

        except Help as err:
            help_entry = (*err.args, '', '<b>%s:</b>' % command_name,
                          get_func_help(bot, command_name, func))
            text = "\n".join(help_entry)
            conv_id = await bot.get_1to1(event.user_id.chat_id) or conv_id

        except Exception as err:
            if raise_exceptions:
                raise

            logger.exception("RUN: %s", command_name)
            text = "<i><b>%s</b> %s</i>" % (command_name, type(err).__name__)

        else:
            if (isinstance(result, str) or
                    (isinstance(result, list) and
                     all([isinstance(item, hangups.ChatMessageSegment)
                          for item in result]))):
                text = result
            elif isinstance(result, tuple) and len(result) == 2:
                conv_id, text = result
            elif (isinstance(result, tuple) and len(result) == 3 and
                  isinstance(result[2], dict)):
                conv_id, text, context = result
            else:
                return result

        await bot.coro_send_message(conv_id, text, context=context)

    def register(self, *args, admin=False, tags=None, final=False, name=None):
        """Decorator for registering command"""

        def wrapper(func):
            func_name = (name or func.__name__).lower()

            if final:
                # wrap command function in coroutine
                func = asyncio.coroutine(func)
                self.commands[func_name] = func
                if admin:
                    self.admin_commands.append(func_name)

            else:
                # just register and return the same function
                plugins.tracking.register_command("admin" if admin else "user",
                                                  [func_name],
                                                  tags=tags)

            return func

        # If there is one (and only one) positional argument and this argument is callable,
        # assume it is the decorator (without any optional keyword arguments)
        if len(args) == 1 and callable(args[0]):
            return wrapper(args[0])
        else:
            return wrapper

    def register_unknown(self, func):
        """Decorator for registering unknown command"""
        self.unknown_command = asyncio.coroutine(func)
        return func

    def register_blocked(self, func):
        """Decorator for registering unknown command"""
        self.blocked_command = asyncio.coroutine(func)
        return func

    def register_argument_preprocessor_group(self, name, preprocessors):
        name_lower = name.lower()
        self.preprocessors[name_lower] = preprocessors
        plugins.tracking.register_command_argument_preprocessors_group(
            name_lower)

# CommandDispatcher singleton
command = CommandDispatcher()

def get_func_help(bot, cmd, func):
    """get a custom help message from memory or parse the doc string of the func

    Args:
        bot: HangupsBot instance
        cmd: string, an existing bot-command
        func: callable, the command function

    Returns:
        string, the custom message or the parsed doc string
    """
    try:
        text = bot.memory.get_by_path(['command_help', cmd]).format(
            bot_cmd=bot.command_prefix)
        return text

    except KeyError:
        pass

    if "__doc__" in dir(func) and func.__doc__:
        _docstring = func.__doc__.strip()
    else:
        return "_{}_".format(_("command help not available"))

    # docstrings: apply (very) limited markdown-like formatting to command help

    # simple bullet lists
    _docstring = re.sub(r'\n +\* +', '\n* ', _docstring)

    # docstrings: handle generic whitespace
    # parse line-breaks: single break -> space; multiple breaks -> paragraph"""
    # XXX: the markdown parser is iffy on line-break processing

    # turn standalone linebreaks into space, preserves multiple linebreaks
    _docstring = re.sub(r"(?<!\n)\n(?= *[^ \t\n\r\f\v\*])", " ", _docstring)
    # convert multiple consecutive spaces into single space
    _docstring = re.sub(r" +", " ", _docstring)
    # convert consecutive linebreaks into double linebreak (pseudo-paragraph)
    _docstring = re.sub(r" *\n\n+ *(?!\*)", "\n\n", _docstring)

    # replace /bot with the first alias in the command handler
    # XXX: [botalias] maintained backward compatibility, please avoid using it
    _docstring = re.sub(r"(?<!\S)\/bot(?!\S)", bot.command_prefix, _docstring)

    return _docstring
