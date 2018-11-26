"""command dispatch for the HangupsBot"""

import asyncio
import logging
import re

import hangups

from hangupsbot.base_models import (
    BotMixin,
    TrackingMixin,
)
from hangupsbot.commands.arguments_parser import ArgumentsParser


logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    'commands_admin': [],

    'commands_user': [],

    'commands_tagged': {},

    'commands.tags.deny-prefix': '!',

    'commands.tags.escalate': False,

    # default timeout for a command-coroutine to return: 5 minutes
    'command_timeout': 5 * 60,
}


class Help(Exception):
    """raise to request the help entry of the current command

    opt: supplied text as string in the arguments will be prepended to the help
    """


class CommandDispatcher(BotMixin, TrackingMixin):
    """Register commands and run them"""

    def __init__(self):
        self.commands = {}
        self.admin_commands = []
        self.unknown_command = None
        self.blocked_command = None

        self.command_tagsets = {}

        self._arguments_parser = ArgumentsParser()
        self.preprocess_arguments = self._arguments_parser.process
        self.register_arg_preprocessor_group = (
            self._arguments_parser.register_preprocessor_group)

    async def clear(self):
        """drop all commands"""
        self.commands.clear()
        self.command_tagsets.clear()
        self.admin_commands.clear()

    @property
    def arguments_parser(self):
        """get the arguments parser

        Returns:
            ArgumentsParser: the current instance
        """
        return self._arguments_parser

    def setup(self):
        """extended init"""
        self.bot.config.set_defaults(DEFAULT_CONFIG)

    def register_tags(self, command_name, tags):
        if isinstance(tags, str):
            tags = {tags}

        if command_name in self.command_tagsets:
            tags = self.command_tagsets[command_name] | tags

        self.command_tagsets[command_name] = tags

    @property
    def deny_prefix(self):
        return self.bot.config.get_option('commands.tags.deny-prefix')

    @property
    def escalate_tagged(self):
        return self.bot.config.get_option('commands.tags.escalate')

    def get_available_commands(self, bot, chat_id, conv_id):
        config_tags_deny_prefix = self.deny_prefix
        config_tags_escalate = self.escalate_tagged

        config_admins = bot.get_config_suboption(conv_id, 'admins')
        is_admin = chat_id in config_admins

        commands_admin = bot.get_config_suboption(conv_id, 'commands_admin')
        commands_user = bot.get_config_suboption(conv_id, 'commands_user')
        commands_tagged = bot.get_config_suboption(conv_id, 'commands_tagged')

        all_commands = set(self.commands)

        # optimization: ignore tags for not loaded commands
        commands_tagged = {cmd: set(tags)
                           for cmd, tags in commands_tagged.items()
                           if cmd in all_commands}

        # combine any plugin-determined tags with the config.json defined ones
        for command_name, tagsets in self.command_tagsets.items():
            config_tags = commands_tagged.setdefault(command_name, set())
            config_tags.update(tagsets)

        if commands_admin is True:
            # all commands are admin-only
            admin_commands = all_commands
            user_commands = set()

        elif commands_user is True:
            # all commands are user-only
            user_commands = all_commands
            admin_commands = set()

        elif commands_user:
            # listed are user commands, others admin-only
            user_commands = set(commands_user).intersection(all_commands)
            admin_commands = all_commands - user_commands

        else:
            # default: follow config["commands_admin"] + plugin settings
            admin_commands = set(commands_admin).intersection(all_commands)
            admin_commands.update(self.admin_commands)
            user_commands = all_commands - admin_commands

        # make admin commands unavailable to non-admin user
        if not is_admin:
            admin_commands.clear()

        if commands_tagged and not is_admin:
            user_tags = frozenset(bot.tags.useractive(chat_id, conv_id))
            denied_commands = set()

            for command_name, tags in commands_tagged.items():
                # raise tagged command access level if escalation required
                if config_tags_escalate and command_name in user_commands:
                    user_commands.remove(command_name)

                for tag in tags:
                    wanted_grant_tags = frozenset((tag,) if isinstance(tag, str)
                                                  else tag)
                    if wanted_grant_tags <= user_tags:
                        admin_commands.add(command_name)

                    revoke_tags = frozenset(config_tags_deny_prefix + tag
                                            for tag in wanted_grant_tags)
                    if revoke_tags <= user_tags:
                        denied_commands.add(command_name)
                        break

            admin_commands -= denied_commands
            user_commands -= denied_commands

        user_commands -= admin_commands  # ensure no overlap

        return {"admin": list(admin_commands), "user": list(user_commands)}

    async def run(self, bot, event, *args, **kwargs):
        """Run a command

        Args:
            bot (hangupsbot.core.HangupsBot): the running instance
            event (hangupsbot.event.ConversationEvent): a message container
            args (str): including the command name in fist place
            kwargs (dict): additional info to the execution including the key
                'raise_exceptions' to raise them instead of sending a message
                '__return_result__' to return all command output

        Returns:
            mixed: command specific output

        Raises:
            KeyError: specified command is unknown
            Help: the kwarg 'raise_exceptions' is set and the command raised
            CancelledError: forward low level cancellation
            TimeoutError: the kwarg 'raise_exceptions' is set and the
                command execution time exceeded the `command_timeout` limit
                which is set in the bot config, default see `DEFAULT_CONFIG`
            Exception: the kwarg 'raise_exceptions' is set to True and the
                command raised any Exception
        """
        command_name = args[0].lower()
        coro = self.commands.get(command_name)
        if coro is None:
            raise KeyError("command {} not found".format(command_name))

        # default: if exceptions occur in a command, output as message
        # supply keyword argument raise_exceptions=True to override behaviour
        raise_exceptions = kwargs.pop("raise_exceptions", False)

        setattr(event, 'command_name', command_name)
        setattr(event, 'command_module', coro.__module__)
        setattr(event, 'command_path', coro.__module__ + '.' + command_name)
        return_result = kwargs.pop("__return_result__", False)

        conv_id = event.conv_id
        context = None
        logger.info(
            'command run %s: %r %r %r',
            id(args), args, kwargs, event
        )
        try:
            result = await asyncio.wait_for(
                coro(bot, event, *args[1:], **kwargs),
                bot.config['command_timeout'])

        except asyncio.CancelledError:
            # shutdown in progress
            logger.warning(
                'command run %s: stopped command execution',
                id(args)
            )
            raise

        except asyncio.TimeoutError:
            if raise_exceptions:
                raise
            text = _('command execution of "{}" timed out').format(command_name)
            logger.error(
                'command run %s: hit timeout of %s sec',
                id(args), bot.config['command_timeout']
            )

        except Help as err:
            if raise_exceptions:
                raise
            help_entry = (*err.args, '', '<b>%s:</b>' % command_name,
                          get_func_help(bot, command_name, coro))
            text = "\n".join(help_entry).strip()
            conv_id = await bot.get_1to1(event.user_id.chat_id) or conv_id

        except Exception as err:  # plugin-error - pylint:disable=broad-except
            if raise_exceptions:
                raise

            logger.exception(
                'command run %s: low level error',
                id(args)
            )
            text = "<i><b>%s</b> %s</i>" % (command_name, type(err).__name__)

        else:
            if return_result:
                return result
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
                self.tracking.register_command("admin" if admin else "user",
                                               [func_name],
                                               tags=tags)

            return func

        # If there is one (and only one) positional argument and this argument
        #  is callable, assume it is the decorator (without any optional keyword
        #  arguments)
        if len(args) == 1 and callable(args[0]):
            return wrapper(args[0])
        return wrapper

    def register_unknown(self, func):
        """Decorator for registering unknown command"""
        self.unknown_command = asyncio.coroutine(func)
        return func

    def register_blocked(self, func):
        """Decorator for registering unknown command"""
        self.blocked_command = asyncio.coroutine(func)
        return func


# CommandDispatcher singleton
command = CommandDispatcher()  # pylint:disable=invalid-name


def get_func_help(bot, cmd, func):
    """get a custom help message from memory or parse the doc string of the func

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        cmd (str): an existing bot-command
        func (mixed): function or coroutine, the command function

    Returns:
        str: the custom message or the parsed doc string
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
