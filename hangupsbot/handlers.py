"""Hangups conversationevent handler with custom pluggables for plugins"""
# pylint:disable=wrong-import-order
import asyncio
import inspect
import logging
import shlex
import time
import uuid

import hangups
import hangups.parsers

import plugins
from commands import command
from event import (GenericEvent, TypingEvent, WatermarkEvent, ConversationEvent)
from exceptions import HangupsBotExceptions

from utils.cache import Cache

logger = logging.getLogger(__name__)


class EventHandler(object):
    """Handle Hangups conversation events

    Args:
        bot: HangupsBot instance
    """
    def __init__(self, bot):
        self.bot = GenericEvent.bot = bot
        self.bot_command = ['/bot']

        self.pluggables = {"allmessages": [],
                           "call": [],
                           "membership": [],
                           "message": [],
                           "rename": [],
                           "history": [],
                           "sending":[],
                           "typing": [],
                           "watermark": [],
                          }

        # timeout for messages to be received for reprocessing: 6hours
        receive_timeout = 60*60*6

        self._reprocessors = Cache(receive_timeout,
                                   increase_on_access=False)

        self._contexts = Cache(receive_timeout,
                               increase_on_access=False)

        self._image_ids = Cache(receive_timeout,
                                increase_on_access=False)

        self._executables = Cache(receive_timeout,
                                  increase_on_access=False)

    async def setup(self, _conv_list):
        """async init part of the handler

        Args:
            _conv_list: hangups.conversation.ConversationList instance
        """
        await plugins.tracking.start({"module": "handlers",
                                      "module.path": "handlers"})

        plugins.register_shared("reprocessor.attach_reprocessor",
                                self.attach_reprocessor)

        plugins.register_shared("chatbridge.behaviours", {})

        self._reprocessors.start()
        self._contexts.start()
        self._image_ids.start()
        self._executables.start()

        plugins.tracking.end()

        _conv_list.on_event.add_observer(self._handle_event)
        _conv_list.on_typing.add_observer(self._handle_status_change)
        _conv_list.on_watermark_notification.add_observer(
            self._handle_status_change)

    def register_handler(self, function, pluggable="message", priority=50):
        """register an event handler

        Args:
            function: callable, the handling function/coro
            pluggable: string, a pluggable of .pluggables
            priority: int, lower priorities receive the event earlier

        Raises:
            KeyError: unknown pluggable specified
        """
        # a handler may use not all args or kwargs, inspect now and filter later
        expected = inspect.signature(function).parameters
        names = list(expected)

        current_plugin = plugins.tracking.current
        self.pluggables[pluggable].append(
            (function, priority, current_plugin["metadata"], expected, names))
        # sort by priority
        self.pluggables[pluggable].sort(key=lambda tup: tup[1])
        plugins.tracking.register_handler(function, pluggable, priority)

    def register_context(self, context):
        """register a message context that can be later attached again

        Args:
            context: dict, no keys are required

        Returns:
            string, a unique identifier for the context
        """
        context_id = None
        while context_id is None or context_id in self._contexts:
            context_id = str(uuid.uuid4())
        self._contexts[context_id] = context
        return context_id

    def register_reprocessor(self, func):
        """register a function that can be called later

        Args:
            func: a callable that takes three args: bot, event, command

        Returns:
            string, a unique identifier for the callable
        """
        reprocessor_id = None
        while reprocessor_id is None or reprocessor_id in self._reprocessors:
            reprocessor_id = str(uuid.uuid4())
        self._reprocessors[reprocessor_id] = func
        return reprocessor_id

    def deregister_plugin(self, module_path):
        """remove previously registered handlers of a given plugin

        Args:
            module_path: string, identifier for a loaded module
        """
        for pluggable in self.pluggables:
            for handler_ in self.pluggables[pluggable]:
                if handler_[2]["module.path"] != module_path:
                    continue
                logger.debug("removing handler %s %s", pluggable, handler_)
                self.pluggables[pluggable].remove(handler_)

    def attach_reprocessor(self, func, return_as_dict=None):
        """connect a func to an identifier to reprocess the event on receive

        reprocessor: map func to a hidden annotation to a message.
        When the message is sent and subsequently received by the bot, it will
        be passed to the func, which can modify the event object by reference
        before it runs through the event processing

        Args:
            func: callable that takes three arguments: bot, event, command
            return_as_dict: legacy code
        """
        #pylint:disable=unused-argument
        reprocessor_id = self.register_reprocessor(func)
        return {"id": reprocessor_id,
                "callable": func}

    # handler core

    async def image_uri_from(self, image_id, callback, *args, **kwargs):
        """retrieve a public url for an image upload

        Args:
            image_id: int, upload id of a previous upload
            callback: coro, awaitable callable
            args: tuple, positional arguments for the callback
            kwargs: dict, keyword arguments for the callback

        Returns:
            boolean, False if no url was awaitable after 60sec, otherwise True
        """
        # TODO(das7pad) refactor plugins to use bot._client.image_upload_raw

        # there was no direct way to resolve an image_id to the public url
        # without posting it first via the api.
        # plugins and functions can establish a short-lived task to wait for the
        # image id to be posted and retrieve the url in an asyncronous way

        ticks = 0
        while ticks < 60:
            if image_id in self._image_ids:
                await callback(self._image_ids[image_id], *args, **kwargs)
                return True
            await asyncio.sleep(1)
            ticks += 1
        return False

    async def run_reprocessor(self, reprocessor_id, event, *args, **kwargs):
        """reprocess the event with the callable that was attached on sending

        Args:
            reprocessor_id: string, a found reprocessor id
            event: hangupsbot event instance
        """
        reprocessor = self._reprocessors.get(reprocessor_id, pop=True)
        if reprocessor is None:
            return

        logger.info("reprocessor uuid found: %s", reprocessor_id)
        result = reprocessor(self.bot, event, reprocessor_id, *args, **kwargs)
        if asyncio.iscoroutinefunction(reprocessor):
            await result

    async def _handle_chat_message(self, event):
        """Handle an incoming conversation event

        - auto-optin opt-outed users if the event is in a 1on1
        - run connected event-reprocessor
        - forward the event to handlers:
            - allmessages, all events
            - message, if user is not the bot user
        - handle the text as command, if the user is not the bot user

        Args:
            event: event.ConversationEvent instance

        Raises:
            exceptions.SuppressEventHandling: do not handle the event at all
        """
        if not event.text:
            return
        if (not event.user.is_self and
                self.bot.conversations[event.conv_id]["type"] == "ONE_TO_ONE"
                and self.bot.user_memory_get(event.user_id.chat_id,
                                             "optout") is True):
            logger.info("auto opt-in for %s", event.user.id_.chat_id)
            await command.run(self.bot, event, *["optout"])
            return

        event.syncroom_no_repeat = False
        event.passthru = {}
        event.context = {}

        # EventAnnotation - allows metadata to survive a trip to Google
        # pylint: disable=protected-access
        for annotation in event.conv_event._event.chat_message.annotation:
            if (annotation.type == 1025 and
                    annotation.value in self._reprocessors):
                await self.run_reprocessor(annotation.value, event)
            elif annotation.type == 1027 and annotation.value in self._contexts:
                event.context = self._contexts[annotation.value]
                if "passthru" in event.context:
                    event.passthru = event.context["passthru"]

        # map image ids to their public uris in absence of any fixed server api
        if (event.passthru
                and "original_request" in event.passthru
                and "image_id" in event.passthru["original_request"]
                and event.passthru["original_request"]["image_id"]
                and len(event.conv_event.attachments) == 1):

            _image_id = event.passthru["original_request"]["image_id"]
            _image_uri = event.conv_event.attachments[0]

            if _image_id not in self._image_ids:
                self._image_ids[_image_id] = _image_uri
                logger.info("associating image_id=%s with %s",
                            _image_id, _image_uri)

        # first occurence of an executable id needs to be handled as an event
        if (event.passthru and event.passthru.get("executable") and
                event.passthru["executable"] not in self._executables):
            original_message = event.passthru["original_request"]["message"]
            linked_hangups_user = event.passthru["original_request"]["user"]
            logger.info("current event is executable: %s", original_message)
            self._executables[event.passthru["executable"]] = time.time()
            event.from_bot = False
            event.text = original_message
            event.user = linked_hangups_user
            event.user_id = linked_hangups_user.id_

        await self.run_pluggable_omnibus("allmessages", self.bot, event,
                                         command)
        if not event.from_bot:
            await self.run_pluggable_omnibus("message", self.bot, event,
                                             command)
            await self._handle_command(event)

    async def _handle_command(self, event):
        """Handle command messages

        Args:
            event: event.ConversationEvent instance
        """
        if not event.text:
            return

        bot = self.bot

        # is commands_enabled?
        config_commands_enabled = bot.get_config_suboption(event.conv_id,
                                                           'commands_enabled')
        tagged_ignore = "ignore" in bot.tags.useractive(event.user_id.chat_id,
                                                        event.conv_id)

        if not config_commands_enabled or tagged_ignore:
            admins_list = bot.get_config_suboption(event.conv_id, 'admins')
            # admins always have commands enabled
            if event.user_id.chat_id not in admins_list:
                return

        # check that a bot alias is used e.g. /bot
        if not event.text.split()[0].lower() in self.bot_command:
            if (bot.conversations[event.conv_id]["type"] == "ONE_TO_ONE"
                    and bot.config.get_option('auto_alias_one_to_one')):
                # Insert default alias if not already present
                event.text = u" ".join((self.bot_command[0], event.text))
            else:
                return

        # Parse message, convert non-breaking space in Latin1 (ISO 8859-1)
        event.text = event.text.replace(u'\xa0', u' ')
        try:
            line_args = shlex.split(event.text, posix=False)
        except ValueError:
            logger.exception('shlex.split failed parsing "%s"', event.text)
            line_args = event.text.split()

        commands = command.get_available_commands(bot, event.user_id.chat_id,
                                                  event.conv_id)

        supplied_command = line_args[1].lower()
        if (supplied_command in commands["user"] or
                supplied_command in commands["admin"]):
            pass
        elif supplied_command in command.commands:
            await command.blocked_command(bot, event, *line_args[1:])
            return
        else:
            await command.unknown_command(bot, event, *line_args[1:])
            return

        # Run command
        results = await command.run(bot, event, *line_args[1:])

        if "acknowledge" in dir(event):
            for id_ in event.acknowledge:
                await self.run_reprocessor(id_, event, results)

    async def run_pluggable_omnibus(self, name, *args, **kwargs):
        """forward args to a group of handler which were registered for the name

        Args:
            name: string, a key in .pluggables
            args: tuple, positional arguments for each handler
            kwargs: dict, keyword arguments for each handler,
                may include '_run_concurrent_' to run them parallel

        Raises:
            KeyError: unknown pluggable specified
            HangupsBotExceptions.SuppressEventHandling: do not handle further
        """
        async def _run_single_handler(function, meta, expected, names):
            """execute a single handler function

            Args:
                function: callable
                meta: dict
                expected: ordered mapping of inspect.Parameter instances
                names: list of strings, keys in expected

            Raises:
                HangupsBotExceptions.SuppressAllHandlers:
                    skip handler of the current type
                HangupsBotExceptions.SuppressEventHandling:
                    skip all handler and do not handle this event further
            """
            message = ["%s: %s.%s" % (name, meta['module.path'],
                                      function.__name__)]
            try:
                # a function may use not all args or kwargs, filter here
                positional = (args[num] for num in range(len(args))
                              if (len(names) > num and (
                                  expected[names[num]].default ==
                                  inspect.Parameter.empty or
                                  names[num] not in kwargs)))
                keyword = {key: value for key, value in kwargs.items()
                           if key in names}

                logger.debug(message[0])
                result = function(*positional, **keyword)
                if asyncio.iscoroutinefunction(function):
                    await result

            except HangupsBotExceptions.SuppressHandler:
                # skip this handler, continue with next
                message.append("SuppressHandler")
                logger.debug(" : ".join(message))
            except HangupsBotExceptions.SuppressAllHandlers:
                # skip all other pluggables, but let the event continue
                message.append("SuppressAllHandlers")
                logger.debug(" : ".join(message))
                raise
            except HangupsBotExceptions.SuppressEventHandling:
                # handle requested to skip all pluggables
                raise
            except: # capture all Exceptions   # pylint: disable=bare-except
                # exception is not related to the handling of this
                # pluggable, log and continue with the next handler
                message.append("args=" + str([str(arg) for arg in args]))
                message.append("kwargs=" + str(kwargs))
                logger.exception(" : ".join(message))

        try:
            if kwargs.pop('_run_concurrent_', False):
                await asyncio.gather(
                    *[_run_single_handler(function, meta, expected, names)
                      for function, dummy, meta, expected, names
                      in self.pluggables[name].copy()])
                return

            for (function, dummy, meta, expected, names
                ) in self.pluggables[name].copy():
                await _run_single_handler(function, meta, expected, names)

        except HangupsBotExceptions.SuppressAllHandlers:
            pass

        except HangupsBotExceptions.SuppressEventHandling:
            # handle requested to do not handle the event at all, skip all
            # handler and do not continue with event handling in the parent
            raise

    async def _handle_event(self, conv_event):
        """Handle conversation events

        Args:
            conv_event: hangups.conversation_event.ConversationEvent instance
        """
        event = ConversationEvent(conv_event)

        if isinstance(conv_event, hangups.ChatMessageEvent):
            pluggable = None

        elif isinstance(conv_event, hangups.MembershipChangeEvent):
            pluggable = "membership"

        elif isinstance(conv_event, hangups.RenameEvent):
            pluggable = "rename"

        elif isinstance(conv_event, hangups.OTREvent):
            pluggable = "history"

        elif isinstance(conv_event, hangups.HangoutEvent):
            pluggable = "call"

        else:
            # Unsupported Events:
            # * GroupLinkSharingModificationEvent
            # https://github.com/tdryer/hangups/blob/master/hangups/conversation_event.py
            logger.warning("unrecognised event type: %s", type(conv_event))
            return

        # rebuild permamem for a conv including conv-name, participants, otr
        await self.bot.conversations.update(event.conv, source="event")

        if pluggable is None:
            asyncio.ensure_future(self._handle_chat_message(event))
            return

        asyncio.ensure_future(self.run_pluggable_omnibus(
            pluggable, self.bot, event, command))

    async def _handle_status_change(self, state_update):
        """run notification handler for a given state_update

        Args:
            state_update: hangups.parsers.TypingStatusMessage or
             hangups.parsers.WatermarkNotification instance
        """
        if isinstance(state_update, hangups.parsers.TypingStatusMessage):
            pluggable = "typing"
            event = TypingEvent(state_update)

        else:
            pluggable = "watermark"
            event = WatermarkEvent(state_update)

        asyncio.ensure_future(self.run_pluggable_omnibus(
            pluggable, self.bot, event, command))


class HandlerBridge:
    """shim for xmikosbot handler decorator"""
    def __init__(self):
        self.bot = None

    def set_bot(self, bot):
        """reference to the bot's actual EventHandler to register handlers"""
        self.bot = bot

    def register(self, *args, priority=10, event=None):
        """Decorator for registering event handler"""

        # make compatible with this bot fork
        scaled_priority = priority * 10 # scale as xmikos uses just 1 to 10
        if event is hangups.ChatMessageEvent:
            event_type = "message"
        elif event is hangups.MembershipChangeEvent:
            event_type = "membership"
        elif event is hangups.RenameEvent:
            event_type = "rename"
        elif isinstance(event, str):
            # accept all kinds of strings, just like register_handler
            event_type = event
        else:
            raise ValueError("unrecognised event {}".format(event))

        def wrapper(func):
            """change the signature of a function to match with the default one

            also register the modified func to the bot event handler

            Note: default signature is func(bot, event, command)

            Args:
                func: callable

            Returns:
                callable, compatible function that matches the defaults
            """
            def thunk(bot, event, dummy):
                """call the original function without the command_"""
                return func(bot, event)

            # Automatically wrap handler function in coroutine
            compatible_func = asyncio.coroutine(thunk)
            # pylint: disable=protected-access
            self.bot._handlers.register_handler(compatible_func,
                                                event_type,
                                                scaled_priority)
            return compatible_func

        # If there is only one positional argument pass and this argument is
        # callable, assume it is the decorator (without any optional keyword
        # arguments)
        if len(args) == 1 and callable(args[0]):
            # make compatible and register the given function
            return wrapper(args[0])
        return wrapper

handler = HandlerBridge()   # pylint: disable=invalid-name
