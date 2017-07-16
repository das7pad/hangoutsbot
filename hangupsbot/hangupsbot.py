#!/usr/bin/env python3
"""chatbot for Google Hangouts"""

import argparse
import asyncio
import gettext
import logging
import logging.config
import os
import shutil
import signal
import sys

import appdirs
import hangups

#NOTE: bring in localization handling for our own modules
#pylint:disable=wrong-import-position,wrong-import-order
gettext.install("hangupsbot", localedir=os.path.join(os.path.dirname(__file__),
                                                     "locale"))

from exceptions import HangupsBotExceptions
from hangups_conversation import HangupsConversation

import config
import handlers
import permamem
import plugins
from commands import command    # import sequence is important here
import tagging
import sinks
import utils
import version

logger = logging.getLogger()

DEFAULT_CONFIG = {
    "bot_introduction": _("<i>Hi there! I'll be using this channel to send "
                          "private messages and alerts. For help, type "
                          "<b>{bot_cmd} help</b>.\nTo keep me quiet, reply with"
                          " <b>{bot_cmd} optout</b>.</i>"),
    # count
    "memory-failsafe_backups": 3,
    # in seconds
    "memory-save_delay": 1,
}

class HangupsBot(object):
    """Hangouts bot listening on all conversations

    Args:
        cookies_path: string, path on disk to stored auth-cookies
        config_path: string, path on disk to the bot configuration json
        memory_path: string, path on disk to the bot memory json
        max_retries: integer, retry count for lowlevel errors
    """
    def __init__(self, cookies_path, config_path, memory_path, max_retries):
        self._client = None
        self._cookies_path = cookies_path
        self._max_retries = max_retries
        self.__retry = 0
        self.__retry_reset = None

        # These are populated by ._on_connect when it's called.
        self.shared = None # safe place to store references to objects
        self._conv_list = None # hangups.ConversationList
        self._user_list = None # hangups.UserList
        self._handlers = None # handlers.py::EventHandler
        self.tags = None # tagging.tags
        self.conversations = None # permamem.ConversationMemory

        self._locales = {}

        # Load config file
        self.config = config.Config(config_path)
        try:
            self.config.load()
        except ValueError:
            logger.exception("FAILED TO LOAD CONFIG FILE")
            sys.exit(1)
        self.config.set_defaults(DEFAULT_CONFIG)

        # set localisation if any defined in
        #  config[language] or ENV[HANGOUTSBOT_LOCALE]
        _language = (self.config.get_option("language")
                     or os.environ.get("HANGOUTSBOT_LOCALE"))
        if _language:
            self.set_locale(_language)

        # load memory file
        _failsafe_backups = self.config.get_option("memory-failsafe_backups")
        _save_delay = self.config.get_option("memory-save_delay")

        logger.info("memory = %s, failsafe = %s, delay = %s",
                    memory_path, _failsafe_backups, _save_delay)
        self.memory = config.Config(memory_path,
                                    failsafe_backups=_failsafe_backups,
                                    save_delay=_save_delay)
        self.memory.logger = logging.getLogger("memory")
        try:
            self.memory.load()
        except (OSError, IOError, ValueError):
            logger.exception("FAILED TO LOAD/RECOVER A MEMORY FILE")
            sys.exit(1)

        self.stop = self._stop
        # Handle signals on Unix
        # (add_signal_handler is not implemented on Windows)
        try:
            loop = asyncio.get_event_loop()
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    signum, lambda: self.stop())         # pylint: disable=W0108
                # lambda necessary here as we overwrite the method .stop
        except NotImplementedError:
            pass

    @property
    def command_prefix(self):
        """get a prefix for bot commands issued via chat

        Returns:
            string
        """
        return self._handlers.bot_command[0]

    def set_locale(self, language_code, reuse=True):
        """update localization

        Args:
            language_code: string, a known translation code
            reuse: string, toggle to True to use a cached translation

        Returns:
            boolean, True on success
        """
        if not reuse or language_code not in self._locales:
            try:
                self._locales[language_code] = gettext.translation(
                    "hangupsbot", languages=[language_code],
                    localedir=os.path.join(os.path.dirname(__file__), "locale"))

                logger.debug("locale loaded: %s", language_code)
            except OSError:
                logger.exception("no translation for %s", language_code)

        if language_code in self._locales:
            self._locales[language_code].install()
            logger.info("locale set to %s", language_code)
            return True

        logger.warning("LOCALE %s is not available", language_code)
        return False

    def register_shared(self, id_, objectref):
        """register a shared object to be called later

        Args:
            id_: string, a unique identifier for the objectref
            objectref: any type, the object to be shared

        Raises:
            RuntimeError: the id_ is already in use
        """
        if id_ in self.shared:
            raise RuntimeError(_("{} already registered in shared").format(id_))

        self.shared[id_] = objectref
        plugins.tracking.register_shared(id_, objectref)

    def call_shared(self, id_, *args, **kwargs):
        """run a registered shared function or get a registered object

        Args:
            id_: string, shared identifier
            args/kwargs: arguments for the shared function

        Returns:
            any type, the return value of the shared function or the shared
                object if the registered object is not callable

        Raises:
            KeyError: the object identifier is unknown
        """
        object_ = self.shared[id_]
        if hasattr(object_, "__call__"):
            return object_(*args, **kwargs)
        return object_

    def run(self):
        """Connect to Hangouts and run bot"""
        def _login():
            """Login to Google account

            Authenticate with saved cookies or prompt for user credentials

            Returns:
                dict, a dict of cookies to authenticate at Google
            """
            try:
                return hangups.get_auth_stdin(self._cookies_path)

            except hangups.GoogleAuthError as err:
                logger.error("LOGIN FAILED: %s", repr(err))
                return False

        cookies = _login()
        if not cookies:
            logger.error("Valid login required, exiting")
            sys.exit(1)

        # Start asyncio event loop
        loop = asyncio.get_event_loop()

        # initialise pluggable framework
        sinks.start(self)

        # initialise plugin and command registration
        plugins.tracking.set_bot(self)
        command.set_bot(self)

        # retries for the hangups longpolling request
        max_retries_longpolling = (self._max_retries
                                   if self._max_retries > 5 else 5)

        # Connect to Hangouts
        # If we are forcefully disconnected, try connecting again
        while self.__retry < self._max_retries:
            self.__retry += 1
            try:
                # (re)create Hangups client
                self._client = hangups.Client(cookies, max_retries_longpolling)
                self._client.on_connect.add_observer(self._on_connect)
                self._client.on_disconnect.add_observer(
                    lambda: logger.warning("Event polling stopped"))
                self._client.on_reconnect.add_observer(
                    lambda: logger.warning("Event polling continued"))

                loop.run_until_complete(self._client.connect())
            except SystemExit:
                raise
            except:                                 # pylint:disable=bare-except
                logger.exception("low-level error")
            else:
                logger.warning("bot is exiting")
                sys.exit(0)

            finally:
                logger.info("bot started unloading")
                loop.run_until_complete(self.__stop())
                loop.run_until_complete(plugins.unload_all(self))

                self.memory.flush()
                self.config.flush()
                logger.info("bot unloaded")

            if self.__retry == self._max_retries:
                # the final retry failed, do not delay the exit
                break

            delay = self.__retry * 5
            logger.info("Waiting %s seconds", delay)
            task = asyncio.ensure_future(asyncio.sleep(delay))

            # a KeyboardInterrupt should cancel the delay task instead
            self.stop = task.cancel

            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                return

            # restore the functionality to stop the bot on KeyboardInterrupt
            self.stop = self._stop
            logger.info("Trying to connect again (try %s of %s)",
                        self.__retry, self._max_retries)

        logger.error("Maximum number of retries reached! Exiting...")
        sys.exit(1)

    async def __stop(self):
        """stop the hangups client"""

        #pylint:disable=protected-access,bare-except
        try:
            # ignore a previous Exception
            if self._client._listen_future._exception is not None:
                logger.info('_stop: discard %s',
                            repr(self._client._listen_future._exception))
            self._client._listen_future._exception = None

        if self.__retry_reset is not None:
            self.__retry_reset.cancel()

            await self._client.disconnect()
        except:                                         # capture any exception
            logger.exception('gracefully stop of hangups client failed')
        finally:
            if not self._client._connector.closed:
                # the connector is still running, close it forcefully
                self._client._connector.close()

    def _stop(self):
        """Disconnect from Hangouts"""
        asyncio.ensure_future(self.__stop())

    def list_conversations(self):
        """List all active conversations"""
        convs = []
        check_ids = []
        missing = []

        try:
            for conv_id in self.conversations.catalog:
                convs.append(self.get_hangups_conversation(conv_id))
                check_ids.append(conv_id)

            hangups_conv_list = self._conv_list.get_all()

            # XXX: run consistency check on reportedly missing conversations from catalog
            for conv in hangups_conv_list:
                if conv.id_ not in check_ids:
                    missing.append(conv.id_)

            logger.info("list_conversations: "
                         "{} from permamem, "
                         "{} from hangups - "
                         "discrepancies: {}".format( len(convs),
                                                     len(hangups_conv_list),
                                                     ", ".join(missing) or "none" ))

        except Exception as e:
            logger.exception("LIST_CONVERSATIONS: failed")
            raise

        return convs

    def get_hangups_user(self, user_id):
        """get a user from the user list

        Args:
            user_id: string, G+ user id; or hangups.user.UserID like object

        Returns:
            a hangups.user.User instance from cached data or a fallback user
        """
        if not isinstance(user_id, hangups.user.UserID):
            chat_id = None
            # ensure a G+ ID as chat_id
            if isinstance(user_id, str) and len(user_id) == 21:
                chat_id = user_id
            elif hasattr(user_id, "chat_id"):
                return self.get_hangups_user(user_id.chat_id)
            user_id = hangups.user.UserID(chat_id=chat_id, gaia_id=chat_id)

        user = self._user_list.get_user(user_id)

        user.is_default = user.name_type == hangups.user.NameType.DEFAULT
        user.definitionsource = None if user.is_default else "hangups"
        return user

    def get_users_in_conversation(self, conv_ids):
        """get hangouts user of a single or multiple conversations

        Args:
            conv_ids: string or list, a single conv or multiple conv_ids

        Returns:
            list, a list of unique hangups.User instances
        """
        if isinstance(conv_ids, str):
            conv_ids = [conv_ids]
        conv_ids = list(set(conv_ids))

        all_users = {}
        for convid in conv_ids:
            conv_data = self.conversations[convid]
            for chat_id in conv_data["participants"]:
                all_users[chat_id] = self.get_hangups_user(chat_id)

        return list(all_users.values())

    def get_config_option(self, option):
        return self.config.get_option(option)

    def get_config_suboption(self, conv_id, option):
        """get an entry in the conv config with a fallback to top level

        Args:
            conv_id: string, conversation identifier
            option: string, third level key as target and also the top level
                key as fallback for a missing key in the path

        Returns:
            any type, the requested value, it's fallback on top level or
                .default if the key does not exist on both level
        """
        return self.config.get_suboption("conversations", conv_id, option)

    def get_memory_option(self, option):
        return self.memory.get_option(option)

    def user_memory_set(self, chat_id, keyname, keyvalue):
        """set a value in the users memory entry and save to memory to file

        Args:
            chat_id: string, G+ id of the user
            keyname: string, new or existing entry in the users memory
            keyvalue: any type, the new value to be set
        """
        self.memory.set_by_path(["user_data", chat_id, keyname], keyvalue)
        self.memory.save()

    def user_memory_get(self, chat_id, keyname):
        """get a memory entry of a given user

        Args:
            chat_id: string, G+ id of the user
            keyname: string, the entry

        Returns:
            any type, the requested value or None if the entry does not exist
        """
        try:
            return self.memory.get_by_path(["user_data", chat_id, keyname],
                                           fallback=False)
        except KeyError:
            return None

    def conversation_memory_set(self, conv_id, keyname, keyvalue):
        """set a value in the conversations memory entry and dump the memory

        Args:
            conv_id: string, conversation identifier
            keyname: string, new or existing entry in the conversations memory
            keyvalue: any type, the new value to be set
        """
        self.memory.set_by_path(["conv_data", conv_id, keyname], keyvalue)
        self.memory.save()

    def conversation_memory_get(self, conv_id, keyname):
        """get a memory entry of a given conversation

        Args:
            conv_id: string, conversation identifier
            keyname: string, the entry

        Returns:
            any type, the requested value or None if the entry does not exist
        """
        try:
            return self.memory.get_by_path(["conv_data", conv_id, keyname],
                                           fallback=False)
        except KeyError:
            return None

    async def get_1to1(self, chat_id, context=None, force=False):
        """find or create a 1-to-1 conversation with specified user

        Args:
            chat_id: string, G+ id of the user
            context: dict, additional info to the request,
                include "initiator_convid" to catch per conv optout
            force: boolean, toggle to get the conv even if the user has optedout

        Returns:
            the HangupsConversation instance of the 1on1, None if no conv can be
                created or False if a 1on1 is not allowed with the user
        """
        if chat_id == self.user_self()["chat_id"]:
            logger.warning("1to1 conversations with myself are not supported",
                           stack_info=True)
            return False

        optout = False if force else self.user_memory_get(chat_id, "optout")
        if optout and (isinstance(optout, bool) or
                       (isinstance(optout, list) and isinstance(context, dict)
                        and context.get("initiator_convid") in optout)):
            logger.debug("get_1on1: user %s has optout", chat_id)
            return False

        memory_1on1 = self.user_memory_get(chat_id, "1on1")

        if memory_1on1 is not None:
            logger.debug("get_1on1: remembered %s for %s",
                         memory_1on1, chat_id)
            return HangupsConversation(self, memory_1on1)

        # create a new 1-to-1 conversation with the designated chat id and send
        # an introduction message as the invitation text
        logger.info("get_1on1: creating 1to1 with %s", chat_id)

        request = hangups.hangouts_pb2.CreateConversationRequest(
            request_header=self.get_request_header(),
            type=hangups.hangouts_pb2.CONVERSATION_TYPE_ONE_TO_ONE,
            client_generated_id=self.get_client_generated_id(),
            invitee_id=[hangups.hangouts_pb2.InviteeID(gaia_id=chat_id)])
        try:
            response = await self.create_conversation(request)
        except hangups.NetworkError:
            logger.exception("GET_1TO1: failed to create 1-to-1 for user %s",
                             chat_id)
            return None

        new_conv_id = response.conversation.conversation_id.id
        logger.info("get_1on1: determined %s for %s", new_conv_id, chat_id)

        # remember the conversation so we do not have to do this again
        self.user_memory_set(chat_id, "1on1", new_conv_id)
        try:
            self._conv_list.get(new_conv_id)
            # do not send the introduction as hangups already knows the conv

        except KeyError:
            conv = hangups.conversation.Conversation(
                self._client, self._user_list, response.conversation)

            # add to hangups cache
            self._conv_list._conv_dict[new_conv_id] = conv #pylint:disable=W0212

            # create the permamem entry for the conversation
            await self.conversations.update(conv, source="1to1creation")

            # send introduction
            introduction = self.config.get_option("bot_introduction").format(
                bot_cmd=self.command_prefix)
            await self.coro_send_message(new_conv_id, introduction)

        return HangupsConversation(self, new_conv_id)

    def initialise_memory(self, key, datatype):
        """initialise the dict for a given key in the datatype in .memory

        Args:
            key: string, identifier for an entry in datatype
            datatype: string, first-level key in memory

        Returns:
            boolean, True if an new entry for the key was created in the
                datatype, otherwise False
        """
        return self.memory.ensure_path([datatype, key])

    async def _on_connect(self):
        """handle connection"""

        def _retry_reset(dummy):
            """schedule a retry counter reset

            Args:
                dummy: hangups.conversation_event.ConversationEvent instance
            """
            async def _delayed_reset():
                """delayed reset of the retry count"""
                try:
                    await asyncio.sleep(self._max_retries)
                except asyncio.CancelledError:
                    return
                self.__retry = 1

            if (self.__retry > 1 and
                    (self.__retry_reset is None or self.__retry_reset.done())):
                self.__retry_reset = asyncio.ensure_future(_delayed_reset())

        logger.debug("connected")

        self.shared = {}
        self.tags = tagging.tags(self)
        self._handlers = handlers.EventHandler(self)
        handlers.handler.set_bot(self) # shim for handler decorator

        # monkeypatch plugins go heere
        # # plugins.load(self, "monkeypatch.something")
        # use only in extreme circumstances
        #  e.g. adding new functionality into hangups library

        self._user_list, self._conv_list = (
            await hangups.build_user_conversation_list(self._client))

        HangupsConversation.setup(self, self._handlers, self._client,
                                  self._user_list, self._conv_list)
        self._conv_list.on_event.add_observer(_retry_reset)

        self.conversations = await permamem.initialise(self)

        await plugins.load(self, "commands.plugincontrol")
        await plugins.load(self, "commands.alias")
        await plugins.load(self, "commands.basic")
        await plugins.load(self, "commands.tagging")
        await plugins.load(self, "commands.permamem")
        await plugins.load(self, "commands.convid")
        await plugins.load(self, "commands.loggertochat")
        await plugins.load_user_plugins(self)


        logger.info("bot initialised")

    @asyncio.coroutine
    def coro_send_message(self, conversation, message, context=None, image_id=None):
        """send a message to hangouts and allow handler to add more targets

        Args:
            conversation: string or hangups conversation like instance
            message: string or a list of hangups.ChatMessageSegment
            context: dict, optional information about the message
            image_id: int or string, upload id of an image to be attached

        Raises:
            ValueError: invalid conversation(id) provided
        """
        if not message and not image_id:
            # at least a message OR an image_id must be supplied
            return

        # update the context
        if not context:
            context = {}

        if "passthru" not in context:
            context['passthru'] = {}

        # get the conversation id
        if hasattr(conversation, "id_"):
            conversation_id = conversation.id_
        elif isinstance(conversation, str):
            conversation_id = conversation
        else:
            raise ValueError('conversation id "%s" is invalid' % conversation)

        broadcast_list = [(conversation_id, message, image_id)]

        # run any sending handlers
        try:
            yield from self._handlers.run_pluggable_omnibus(
                "sending", self, broadcast_list, context)
        except HangupsBotExceptions.SuppressEventHandling:
            logger.info("message sending: SuppressEventHandling")
            return

        logger.debug("message sending: global context=%s", context)

        for response in broadcast_list:
            logger.debug("message sending: %s", response[0])

            # use a fake Hangups Conversation having a fallback to permamem
            conv = HangupsConversation(self, response[0])

            try:
                yield from conv.send_message(response[1],
                                             image_id=response[2],
                                             context=context)
            except hangups.NetworkError:
                logger.exception("CORO_SEND_MESSAGE: error sending %s",
                                 response)


    @asyncio.coroutine
    def coro_send_to_user(self, chat_id, message, context=None):
        """send a message to a specific user's 1-to-1

        the user must have already been seen elsewhere by the bot

        Args:
            chat_id: users G+ id
            message: string or a list of hangups.ChatMessageSegment
            context: dict, optional information about the message

        Returns:
            boolean, True if the message was sent,
                otherwise False - unknown user, optouted or error on .get_1to1()
        """
        if not self.memory.exists(["user_data", chat_id, "_hangups"]):
            logger.info("%s is not a valid user", chat_id)
            return False

        conv_1on1 = yield from self.get_1to1(chat_id)

        if conv_1on1 is False:
            logger.info("user %s is optout, no message sent", chat_id)
            return True

        elif conv_1on1 is None:
            logger.info("1-to-1 for user %s is unavailable", chat_id)
            return False

        logger.info("sending message to user %s via %s",
                    chat_id, conv_1on1.id_)

        yield from self.coro_send_message(conv_1on1, message, context=context)
        return True


    @asyncio.coroutine
    def coro_send_to_user_and_conversation(self, chat_id, conv_id,
                                           message_private,
                                           message_public=None,
                                           context=None):
        """send a message to a user's 1-to-1 with a hint in the public chat

        if no 1-to-1 is available, send everything to the public chat

        Args:
            chat_id: users G+ id
            message: string or a list of hangups.ChatMessageSegment
            context: dict, optional information about the message
        """
        conv_1on1 = yield from self.get_1to1(chat_id)

        full_name = self.get_hangups_user(chat_id).full_name

        responses = {
            "standard":
                None, # no public message
            "optout":
                _("<i>{}, you are currently opted-out. Private message me or "
                  "enter <b>{} optout</b> to get me to talk to you.</i>"
                 ).format(full_name, self.command_prefix),
            "no1to1":
                _("<i>{}, before I can help you, you need to private message me"
                  " and say hi.</i>").format(full_name, self.command_prefix)
        }

        keys = ["standard", "optout", "no1to1"]
        if (isinstance(message_public, dict)
                and all([key in keys for key in message_public])):
            responses = message_public
        elif isinstance(message_public, list) and len(message_public) == 3:
            for supplied in message_public:
                responses[keys.pop(0)] = supplied
        else:
            responses["standard"] = str(message_public)

        public_message = None
        if conv_1on1:
            yield from self.coro_send_message(conv_1on1, message_private,
                                              context)

            # send a public message, if supplied
            if conv_1on1.id_ != conv_id and responses["standard"]:
                public_message = responses["standard"]

        else:
            if isinstance(conv_1on1, bool) and responses["optout"]:
                public_message = responses["optout"]

            elif responses["no1to1"]:
                # isinstance(conv_1on1, None)
                public_message = responses["no1to1"]

        yield from self.coro_send_message(conv_id, public_message,
                                          context=context)

    def user_self(self):
        """get information about the bot user

        Returns:
            dict, keys are "chat_id", "full_name" and "email"
        """
        myself = {
            "chat_id": None,
            "full_name": None,
            "email": None
        }
        user = self._user_list._self_user   # pylint: disable=W0212

        myself["chat_id"] = user.id_.chat_id

        if user.full_name:
            myself["full_name"] = user.full_name
        if user.emails and user.emails[0]:
            myself["email"] = user.emails[0]

        return myself

    def __getattr__(self, attr):
        """bridge base requests to the hangups client

        Args:
            attr: string, method name of hangups.client.Client

        Returns:
            callable, the requested method if it is not private

        Raises:
            NotImplementedError: the method is private or not implemented
        """
        if attr and attr[0] != "_" and hasattr(self._client, attr):
            return getattr(self._client, attr)
        raise NotImplementedError()


def configure_logging(args):
    """Configure Logging

    If the user specified a logging config file, open it, and
    fail if unable to open. If not, attempt to open the default
    logging config file. If that fails, move on to basic
    log configuration.
    """

    log_level = "DEBUG" if args.debug else "INFO"

    default_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": ("%(asctime)s %(levelname)s %(name)s: %(message)s"),
                "datefmt": "%H:%M:%S"
                },
            "default": {
                "format": ("%(asctime)s %(levelname)s %(name)s: %(message)s"),
                "datefmt": "%Y-%m-%d %H:%M:%S"
                }
            },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "level": "INFO",
                "formatter": "console"
                },
            "file": {
                "class": "logging.FileHandler",
                "filename": args.log,
                "level": log_level,
                "formatter": "default",
                },
                }
            },
        "loggers": {
            # root logger
            "": {
                "handlers": ["file", "console"],
                "level": log_level
                },

            # requests is freakishly noisy
            "requests": {"level": "INFO"},

            "hangups": {"level": "WARNING"},

            # ignore the addition of fallback users
            "hangups.user": {"level": "ERROR"},

            # do not log disconnects twice, we already attach a logger to
            # ._client.on_disconnect
            "hangups.channel": {"level": "ERROR"},

            # asyncio's debugging logs are VERY noisy, so adjust the log level
            "asyncio": {"level": "WARNING"},

            }
        }

    logging_config = default_config

    # Temporarily bring in the configuration file, just so we can configure
    # logging before bringing anything else up. There is no race internally,
    # if logging() is called before configured, it outputs to stderr, and
    # we will configure it soon enough
    bootcfg = config.Config(args.config)
    bootcfg.load()
    if bootcfg.exists(["logging.system"]):
        logging_config = bootcfg["logging.system"]

    if "extras.setattr" in logging_config:
        for class_attr, value in logging_config["extras.setattr"].items():
            try:
                [modulepath, classname, attribute] = class_attr.rsplit(".", 2)
                try:
                    setattr(utils.class_from_name(modulepath, classname),
                            attribute, value)
                except ImportError:
                    logging.error("module %s not found", modulepath)
                except AttributeError:
                    logging.error("%s in %s not found", classname, modulepath)
            except ValueError:
                logging.error("format should be <module>.<class>.<attribute>")

    logging.config.dictConfig(logging_config)

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

def main():
    """Main entry point"""
    # Build default paths for files.
    dirs = appdirs.AppDirs("hangupsbot", "hangupsbot")
    default_log_path = os.path.join(dirs.user_data_dir, "hangupsbot.log")
    default_cookies_path = os.path.join(dirs.user_data_dir, "cookies.json")
    default_config_path = os.path.join(dirs.user_data_dir, "config.json")
    default_memory_path = os.path.join(dirs.user_data_dir, "memory.json")

    # Configure argument parser
    parser = argparse.ArgumentParser(
        prog="hangupsbot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-d", "--debug", action="store_true",
                        help=_("log detailed debugging messages"))
    parser.add_argument("--log", default=default_log_path,
                        help=_("log file path"))
    parser.add_argument("--cookies", default=default_cookies_path,
                        help=_("cookie storage path"))
    parser.add_argument("--memory", default=default_memory_path,
                        help=_("memory storage path"))
    parser.add_argument("--config", default=default_config_path,
                        help=_("config storage path"))
    parser.add_argument("--retries", default=5, type=int,
                        help=_("Maximum disconnect / reconnect retries before "
                               "quitting"))
    parser.add_argument("--version", action="version",
                        version="%(prog)s {}".format(version.__version__),
                        help=_("show program\"s version number and exit"))
    args = parser.parse_args()


    # Create all necessary directories.
    for path in [args.log, args.cookies, args.config, args.memory]:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            try:
                os.makedirs(directory)
            except OSError as err:
                sys.exit(_("Failed to create directory: %s"), err)

    # If there is no config file in user data directory, copy default one there
    if not os.path.isfile(args.config):
        try:
            shutil.copy(
                os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]),
                                             "config.json")),
                args.config)
        except (OSError, IOError) as err:
            sys.exit(_("Failed to copy default config file: %s"), err)

    configure_logging(args)

    # initialise the bot
    bot = HangupsBot(args.cookies, args.config, args.memory, args.retries)

    # start the bot
    bot.run()

if __name__ == "__main__":
    main()
