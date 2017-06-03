import logging
import shlex
import asyncio
import inspect
import time
import uuid

import hangups

import plugins
from commands import command


logger = logging.getLogger(__name__)


class EventHandler:
    """Handle Hangups conversation events"""

    def __init__(self, bot, bot_command='/bot'):
        self.bot = bot
        self.bot_command = bot_command

        self._prefix_reprocessor = "uuid://"
        self._reprocessors = {}

        self._passthrus = {}
        self._contexts = {}
        self._image_ids = {}
        self._executables = {}

        self.pluggables = { "allmessages": [],
                            "call": [],
                            "membership": [],
                            "message": [],
                            "rename": [],
                            "history": [],
                            "sending":[],
                            "typing": [],
                            "watermark": [] }

        bot.register_shared( 'reprocessor.attach_reprocessor',
                             self.attach_reprocessor,
                             forgiving=True )

        bot.register_shared( 'chatbridge.behaviours',
                             {},
                             forgiving=True )

    def register_handler(self, function, type="message", priority=50):
        """registers extra event handlers"""
        if type in ["allmessages", "call", "membership", "message", "rename", "history", "typing", "watermark"]:
            if not asyncio.iscoroutine(function):
                # transparently convert into coroutine
                function = asyncio.coroutine(function)
        elif type in ["sending"]:
            if asyncio.iscoroutine(function):
                raise RuntimeError("{} handler cannot be a coroutine".format(type))
        else:
            raise ValueError("unknown event type for handler: {}".format(type))

        current_plugin = plugins.tracking.current()
        self.pluggables[type].append((function, priority, current_plugin["metadata"]))
        self.pluggables[type].sort(key=lambda tup: tup[1])

        plugins.tracking.register_handler(function, type, priority)

    def register_passthru(self, variable):
        _id = str(uuid.uuid4())
        self._passthrus[_id] = variable
        return _id

    def register_context(self, variable):
        _id = str(uuid.uuid4())
        self._contexts[_id] = variable
        return _id

    def register_reprocessor(self, callable):
        _id = str(uuid.uuid4())
        self._reprocessors[_id] = callable
        return _id

    def attach_reprocessor(self, callable, return_as_dict=False):
        """reprocessor: map callable to a special hidden context link that can be added anywhere 
        in a message. when the message is sent and subsequently received by the bot, it will be 
        passed to the callable, which can modify the event object by reference
        """
        _id = self.register_reprocessor(callable)
        context_fragment = '<a href="' + self._prefix_reprocessor + _id + '"> </a>'
        if return_as_dict:
            return { "id": _id,
                     "callable": callable,
                     "fragment": context_fragment }
        else:
            return context_fragment

    """handler core"""

    @asyncio.coroutine
    def image_uri_from(self, image_id, callback, *args, **kwargs):
        """XXX: there isn't a direct way to resolve an image_id to the public url without
        posting it first via the api. other plugins and functions can establish a short-lived
        task to wait for the image id to be posted, and retrieve the url in an asyncronous way"""

        ticks = 0
        while True:
            if image_id not in self._image_ids:
                yield from asyncio.sleep(1)
                ticks = ticks + 1
                if ticks > 60:
                    return False
            else:
                yield from callback(self._image_ids[image_id], *args, **kwargs)
                return True

    @asyncio.coroutine
    def run_reprocessor(self, id, event, *args, **kwargs):
        if id in self._reprocessors:
            is_coroutine = asyncio.iscoroutinefunction(self._reprocessors[id])
            logger.info("reprocessor uuid found: {} coroutine={}".format(id, is_coroutine))
            if is_coroutine:
                yield from self._reprocessors[id](self.bot, event, id, *args, **kwargs)
            else:
                self._reprocessors[id](self.bot, event, id, *args, **kwargs)
            del self._reprocessors[id]

    @asyncio.coroutine
    def handle_chat_message(self, event):
        """Handle conversation event"""
        if event.text:
            if event.user.is_self:
                event.from_bot = True
            else:
                event.from_bot = False

            """EventAnnotation - allows metadata to survive a trip to Google"""

            event.passthru = {}
            event.context = {}
            for annotation in event.conv_event._event.chat_message.annotation:
                if annotation.type == 1025:
                    # reprocessor - process event with hidden context from handler.attach_reprocessor()
                    yield from self.run_reprocessor(annotation.value, event)
                elif annotation.type == 1026:
                    if annotation.value in self._passthrus:
                        event.passthru = self._passthrus[annotation.value]
                        del self._passthrus[annotation.value]
                elif annotation.type == 1027:
                    if annotation.value in self._contexts:
                        event.context = self._contexts[annotation.value]
                        del self._contexts[annotation.value]

            if len(event.conv_event.segments) > 0:
                for segment in event.conv_event.segments:
                    if segment.link_target:
                        if segment.link_target.startswith(self._prefix_reprocessor):
                            _id = segment.link_target[len(self._prefix_reprocessor):]
                            yield from self.run_reprocessor(_id, event)

            """auto opt-in - opted-out users who chat with the bot will be opted-in again"""
            if not event.from_bot and self.bot.conversations.catalog[event.conv_id]["type"] == "ONE_TO_ONE":
                if self.bot.memory.exists(["user_data", event.user.id_.chat_id, "optout"]):
                    optout = self.bot.memory.get_by_path(["user_data", event.user.id_.chat_id, "optout"])
                    if isinstance(optout, bool) and optout:
                        yield from command.run(self.bot, event, *["optout"])
                        logger.info("auto opt-in for {}".format(event.user.id_.chat_id))
                        return

            """map image ids to their public uris in absence of any fixed server api
               XXX: small memory leak over time as each id gets cached indefinitely"""

            if( event.passthru
                    and "original_request" in event.passthru
                    and "image_id" in event.passthru["original_request"]
                    and event.passthru["original_request"]["image_id"]
                    and len(event.conv_event.attachments) == 1 ):

                _image_id = event.passthru["original_request"]["image_id"]
                _image_uri = event.conv_event.attachments[0]

                if _image_id not in self._image_ids:
                    self._image_ids[_image_id] = _image_uri
                    logger.info("associating image_id={} with {}".format(_image_id, _image_uri))

            """first occurence of an actual executable id needs to be handled as an event
               XXX: small memory leak over time as each id gets cached indefinitely"""

            if( event.passthru and "executable" in event.passthru and event.passthru["executable"] ):
                if event.passthru["executable"] not in self._executables:
                    original_message = event.passthru["original_request"]["message"]
                    linked_hangups_user = event.passthru["original_request"]["user"]
                    logger.info("current event is executable: {}".format(original_message))
                    self._executables[event.passthru["executable"]] = time.time()
                    event.from_bot = False
                    event.text = original_message
                    event.user = linked_hangups_user

            yield from self.run_pluggable_omnibus("allmessages", self.bot, event, command)
            if not event.from_bot:
                yield from self.run_pluggable_omnibus("message", self.bot, event, command)
                yield from self.handle_command(event)

    @asyncio.coroutine
    def handle_command(self, event):
        """Handle command messages"""

        # is commands_enabled?

        config_commands_enabled = self.bot.get_config_suboption(event.conv_id, 'commands_enabled')
        tagged_ignore = "ignore" in self.bot.tags.useractive(event.user_id.chat_id, event.conv_id)

        if not config_commands_enabled or tagged_ignore:
            admins_list = self.bot.get_config_suboption(event.conv_id, 'admins') or []
            # admins always have commands enabled
            if event.user_id.chat_id not in admins_list:
                return

        # ensure bot alias is always a list
        if not isinstance(self.bot_command, list):
            self.bot_command = [self.bot_command]

        # check that a bot alias is used e.g. /bot
        if not event.text.split()[0].lower() in self.bot_command:
            if self.bot.conversations.catalog[event.conv_id]["type"] == "ONE_TO_ONE" and self.bot.get_config_option('auto_alias_one_to_one'):
                event.text = u" ".join((self.bot_command[0], event.text)) # Insert default alias if not already present
            else:
                return

        # Parse message
        event.text = event.text.replace(u'\xa0', u' ') # convert non-breaking space in Latin1 (ISO 8859-1)
        try:
            line_args = shlex.split(event.text, posix=False)
        except Exception as e:
            logger.exception(e)
            yield from self.bot.coro_send_message(event.conv, _("{}: {}").format(
                event.user.full_name, str(e)))
            return

        # Test if command length is sufficient
        if len(line_args) < 2:
            config_silent = bot.get_config_suboption(event.conv.id_, 'silentmode')
            tagged_silent = "silent" in bot.tags.useractive(event.user_id.chat_id, event.conv.id_)
            if not (config_silent or tagged_silent):
                yield from self.bot.coro_send_message(event.conv, _('{}: Missing parameter(s)').format(
                    event.user.full_name))
            return
        
        commands = command.get_available_commands(self.bot, event.user.id_.chat_id, event.conv_id)

        supplied_command = line_args[1].lower()
        if supplied_command in commands["user"]:
            pass
        elif supplied_command in commands["admin"]:
            pass
        elif supplied_command in command.commands:
            yield from command.blocked_command(self.bot, event, *line_args[1:])
            return
        else:
            yield from command.unknown_command(self.bot, event, *line_args[1:])
            return

        # Run command
        results = yield from command.run(self.bot, event, *line_args[1:])

        if "acknowledge" in dir(event):
            for id in event.acknowledge:
                yield from self.run_reprocessor(id, event, results)

    @asyncio.coroutine
    def handle_chat_membership(self, event):
        """handle conversation membership change"""
        yield from self.run_pluggable_omnibus("membership", self.bot, event, command)

    @asyncio.coroutine
    def handle_chat_rename(self, event):
        """handle conversation name change"""
        yield from self.run_pluggable_omnibus("rename", self.bot, event, command)

    @asyncio.coroutine
    def handle_chat_history(self, event):
        """handle conversation OTR status change"""
        yield from self.run_pluggable_omnibus("history", self.bot, event, command)

    @asyncio.coroutine
    def handle_call(self, event):
        """handle incoming calls (voice/video)"""
        yield from self.run_pluggable_omnibus("call", self.bot, event, command)

    @asyncio.coroutine
    def handle_typing_notification(self, event):
        """handle changes in typing state"""
        yield from self.run_pluggable_omnibus("typing", self.bot, event, command)

    @asyncio.coroutine
    def handle_watermark_notification(self, event):
        """handle watermark updates"""
        yield from self.run_pluggable_omnibus("watermark", self.bot, event, command)

    @asyncio.coroutine
    def run_pluggable_omnibus(self, name, *args, **kwargs):
        if name in self.pluggables:
            try:
                for function, priority, plugin_metadata in self.pluggables[name]:
                    message = ["{}: {}.{}".format(
                                name,
                                plugin_metadata["module.path"],
                                function.__name__)]

                    try:
                        """accepted handler signatures:
                        coroutine(bot, event, command)
                        coroutine(bot, event)
                        function(bot, event, context)
                        function(bot, event)
                        """
                        _expected = list(inspect.signature(function).parameters)
                        _passed = args[0:len(_expected)]
                        if asyncio.iscoroutinefunction(function):
                            message.append("coroutine")
                            logger.debug(" : ".join(message))
                            yield from function(*_passed)
                        else:
                            message.append("function")
                            logger.debug(" : ".join(message))
                            function(*_passed)
                    except self.bot.Exceptions.SuppressHandler:
                        # skip this pluggable, continue with next
                        message.append("SuppressHandler")
                        logger.debug(" : ".join(message))
                        pass
                    except (self.bot.Exceptions.SuppressEventHandling,
                            self.bot.Exceptions.SuppressAllHandlers):
                        # skip all pluggables, decide whether to handle event at next level
                        raise
                    except:
                        message = " : ".join(message)
                        logger.exception(message)

            except self.bot.Exceptions.SuppressAllHandlers:
                # skip all other pluggables, but let the event continue
                message.append("SuppressAllHandlers")
                logger.debug(" : ".join(message))

            except:
                raise

class HandlerBridge:
    """shim for xmikosbot handler decorator"""

    def set_bot(self, bot):
        """shim requires a reference to the bot's actual EventHandler to register handlers"""
        self.bot = bot

    def register(self, *args, priority=10, event=None):
        """Decorator for registering event handler"""

        # make compatible with this bot fork
        scaled_priority = priority * 10 # scale for compatibility - xmikos range 1 - 10
        if event is hangups.ChatMessageEvent:
            event_type = "message"
        elif event is hangups.MembershipChangeEvent:
            event_type = "membership"
        elif event is hangups.RenameEvent:
            event_type = "rename"
        elif event is hangups.OTREvent:
            event_type = "history"
        elif type(event) is str:
            event_type = str # accept all kinds of strings, just like register_handler
        else:
            raise ValueError("unrecognised event {}".format(event))

        def wrapper(func):
            def thunk(bot, event, command):
                # command is an extra parameter supplied in this fork
                return func(bot, event)

            # Automatically wrap handler function in coroutine
            compatible_func = asyncio.coroutine(thunk)
            self.bot._handlers.register_handler(compatible_func, event_type, scaled_priority)
            return compatible_func

        # If there is one (and only one) positional argument and this argument is callable,
        # assume it is the decorator (without any optional keyword arguments)
        if len(args) == 1 and callable(args[0]):
            return wrapper(args[0])
        else:
            return wrapper

handler = HandlerBridge()
