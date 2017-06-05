#!/usr/bin/env python3
import appdirs, argparse, asyncio, gettext, logging, logging.config, os, shutil, signal, sys, time

import hangups

import hangups_shim
from exceptions import HangupsBotExceptions
from hangups_conversation import HangupsConversation

import config
import handlers
import version

import permamem
import tagging

import sinks
import plugins

from commands import command
from permamem import conversation_memory
from utils import simple_parse_to_segments, class_from_name


gettext.install('hangupsbot', localedir=os.path.join(os.path.dirname(__file__), 'locale'))


logger = logging.getLogger()

DEFAULT_CONFIG = {
    "bot_introduction": _("<i>Hi there! I'll be using this channel to send "
                          "private messages and alerts. For help, type "
                          "<b>{bot_cmd} help</b>.\nTo keep me quiet, reply with"
                          " <b>{bot_cmd} optout</b>.</i>"),
    "memory-failsafe_backups": 3,
    # in seconds
    "memory-save_delay": 1,
}

class HangupsBot(object):
    """Hangouts bot listening on all conversations"""
    def __init__(self, cookies_path, config_path, memory_path, max_retries=5):
        self.shared = {} # safe place to store references to objects

        self._client = None
        self._cookies_path = cookies_path
        self._max_retries = max_retries

        # These are populated by on_connect when it's called.
        self._conv_list = None # hangups.ConversationList
        self._user_list = None # hangups.UserList
        self._handlers = None # handlers.py::EventHandler

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
        self.memory.logger = logging.getLogger('memory')
        try:
            self.memory.load()
        except (OSError, IOError, ValueError):
            logger.exception("FAILED TO LOAD/RECOVER A MEMORY FILE")
            sys.exit(1)

        # Handle signals on Unix
        # (add_signal_handler is not implemented on Windows)
        try:
            loop = asyncio.get_event_loop()
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, lambda: self.stop())
        except NotImplementedError:
            pass


    def set_locale(self, language_code, reuse=True):
        if not reuse or language_code not in self._locales:
            try:
                self._locales[language_code] = gettext.translation('hangupsbot', localedir=os.path.join(os.path.dirname(__file__), 'locale'), languages=[language_code])
                logger.debug("locale loaded: {}".format(language_code))
            except OSError:
                logger.exception("no translation for {}".format(language_code))

        if language_code in self._locales:
            self._locales[language_code].install()
            logger.info("locale: {}".format(language_code))
            return True

        else:
            logger.warning("LOCALE: {}".format(language_code))
            return False


    def register_shared(self, id, objectref, forgiving=False):
        if id in self.shared:
            message = _("{} already registered in shared").format(id)
            if forgiving:
                logger.info(message)
            else:
                raise RuntimeError(message)

        self.shared[id] = objectref
        plugins.tracking.register_shared(id, objectref, forgiving=forgiving)

    def call_shared(self, id, *args, **kwargs):
        object = self.shared[id]
        if hasattr(object, '__call__'):
            return object(*args, **kwargs)
        else:
            return object

    def login(self, cookies_path):
        """Login to Google account"""
        # Authenticate Google user and save auth cookies
        # (or load already saved cookies)
        try:
            cookies = hangups.auth.get_auth_stdin(cookies_path)
            return cookies

        except hangups.GoogleAuthError as e:
            logger.exception("LOGIN FAILED")
            return False

    def run(self):
        """Connect to Hangouts and run bot"""
        cookies = self.login(self._cookies_path)
        if cookies:
            # Start asyncio event loop
            loop = asyncio.get_event_loop()

            # initialise pluggable framework
            sinks.start(self)

            # Connect to Hangouts
            # If we are forcefully disconnected, try connecting again
            for retry in range(self._max_retries):
                try:
                    # create Hangups client (recreate if its a retry)
                    self._client = hangups.Client(cookies)
                    self._client.on_connect.add_observer(self._on_connect)
                    self._client.on_disconnect.add_observer(self._on_disconnect)

                    loop.run_until_complete(self._client.connect())

                    logger.info("bot is exiting")

                    loop.run_until_complete(plugins.unload_all(self))

                    self.memory.flush()
                    self.config.flush()

                    sys.exit(0)
                except Exception as e:
                    logger.exception("CLIENT: unrecoverable low-level error")
                    print('Client unexpectedly disconnected:\n{}'.format(e))

                    loop.run_until_complete(plugins.unload_all(self))

                    logger.info('Waiting {} seconds...'.format(5 + retry * 5))
                    time.sleep(5 + retry * 5)
                    logger.info('Trying to connect again (try {} of {})...'.format(retry + 1, self._max_retries))

            logger.error('Maximum number of retries reached! Exiting...')

        logger.error("Valid login required, exiting")

        sys.exit(1)

    def stop(self):
        """Disconnect from Hangouts"""
        asyncio.async(
            self._client.disconnect()
        ).add_done_callback(lambda future: future.result())

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
            elif hasattr(user_id, 'chat_id'):
                return self.get_hangups_user(user_id.chat_id)
            user_id = hangups.user.UserID(chat_id=chat_id, gaia_id=chat_id)

        user = self._user_list.get_user(user_id)

        user.is_default = user.name_type == hangups.user.NameType.DEFAULT
        user.definitionsource = None if user.is_default else "hangups"
        return user

    def get_users_in_conversation(self, conv_ids):
        """list all unique users in supplied conv_id or list of conv_ids"""

        if isinstance(conv_ids, str):
            conv_ids = [conv_ids]
        conv_ids = list(set(conv_ids))

        all_users = {}
        for convid in conv_ids:
            conv_data = self.conversations.catalog[convid]
            for chat_id in conv_data["participants"]:
                all_users[chat_id] = self.get_hangups_user(chat_id) # by key for uniqueness

        all_users = list(all_users.values())

        return all_users

    def get_config_option(self, option):
        return self.config.get_option(option)

    def get_config_suboption(self, conv_id, option):
        return self.config.get_suboption("conversations", conv_id, option)

    def get_memory_option(self, option):
        return self.memory.get_option(option)

    def get_memory_suboption(self, user_id, option):
        return self.memory.get_suboption("user_data", user_id, option)

    def user_memory_set(self, chat_id, keyname, keyvalue):
        self.initialise_memory(chat_id, "user_data")
        self.memory.set_by_path(["user_data", chat_id, keyname], keyvalue)
        self.memory.save()

    def user_memory_get(self, chat_id, keyname):
        value = None
        try:
            self.initialise_memory(chat_id, "user_data")
            value = self.memory.get_by_path(["user_data", chat_id, keyname])
        except KeyError:
            pass
        return value

    def conversation_memory_set(self, conv_id, keyname, keyvalue):
        self.initialise_memory(conv_id, "conv_data")
        self.memory.set_by_path(["conv_data", conv_id, keyname], keyvalue)
        self.memory.save()

    def conversation_memory_get(self, conv_id, keyname):
        value = None
        try:
            self.initialise_memory(conv_id, "conv_data")
            value = self.memory.get_by_path(["conv_data", conv_id, keyname])
        except KeyError:
            pass
        return value

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
            self.conversations.update(conv, source="1to1creation")

            # send introduction
            introduction = self.config.get_option("bot_introduction").format(
                bot_cmd=self.command_prefix)
            await self.coro_send_message(new_conv_id, introduction)

        return HangupsConversation(self, new_conv_id)

    def initialise_memory(self, chat_id, datatype):
        modified = False

        if not self.memory.exists([datatype]):
            # create the datatype grouping if it does not exist
            self.memory.set_by_path([datatype], {})
            modified = True

        if not self.memory.exists([datatype, chat_id]):
            # create the memory
            self.memory.set_by_path([datatype, chat_id], {})
            modified = True

        return modified


    @asyncio.coroutine
    def _on_connect(self):
        """handle connection/reconnection"""

        logger.debug("connected")

        plugins.tracking.set_bot(self)
        command.set_tracking(plugins.tracking)
        command.set_bot(self)

        self.tags = tagging.tags(self)
        self._handlers = handlers.EventHandler(self)
        handlers.handler.set_bot(self) # shim for handler decorator

        """
        monkeypatch plugins go heere
        # plugins.load(self, "monkeypatch.something")
        use only in extreme circumstances e.g. adding new functionality into hangups library
        """

        #self._user_list = yield from hangups.user.build_user_list(self._client)

        self._user_list, self._conv_list = (
            yield from hangups.build_user_conversation_list(self._client)
        )

        self.conversations = await permamem.initialise(self)

        plugins.load(self, "commands.plugincontrol")
        plugins.load(self, "commands.basic")
        plugins.load(self, "commands.tagging")
        plugins.load(self, "commands.permamem")
        plugins.load(self, "commands.convid")
        plugins.load(self, "commands.loggertochat")
        plugins.load_user_plugins(self)

        self._conv_list.on_event.add_observer(self._handlers.handle_event)
        self._client.on_state_update.add_observer(
            self._handlers.handle_status_change)

        logger.info("bot initialised")

    def _on_disconnect(self):
        """Handle disconnecting"""
        logger.info('Connection lost!')

    @asyncio.coroutine
    def coro_send_message(self, conversation, message, context=None, image_id=None):
        if not message and not image_id:
            # at least a message OR an image_id must be supplied
            return

        # get the context

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
            raise ValueError('could not identify conversation id')

        broadcast_list = [(conversation_id, message, image_id)]

        # run any sending handlers

        try:
            yield from self._handlers.run_pluggable_omnibus("sending", self, broadcast_list, context)
        except HangupsBotExceptions.SuppressEventHandling:
            logger.info("message sending: SuppressEventHandling")
            return
        except:
            raise

        logger.debug("message sending: global context = {}".format(context))

        # begin message sending.. for REAL!

        for response in broadcast_list:
            logger.debug("message sending: {}".format(response[0]))

            # use a fake Hangups Conversation having a fallback to permamem
            conv = HangupsConversation(self, response[0])

            try:
                yield from _fc.send_message( response[1],
                                             image_id = response[2],
                                             context = context )
            except hangups.NetworkError as e:
                logger.exception("CORO_SEND_MESSAGE: error sending {}".format(response[0]))


    @asyncio.coroutine
    def coro_send_to_user(self, chat_id, html, context=None):
        """
        send a message to a specific user's 1-to-1
        the user must have already been seen elsewhere by the bot (have a permanent memory entry)
        """
        if not self.memory.exists(["user_data", chat_id, "_hangups"]):
            logger.debug("{} is not a valid user".format(chat_id))
            return False

        conversation = yield from self.get_1to1(chat_id)

        if conversation is False:
            logger.info("user {} is optout, no message sent".format(chat_id))
            return True

        elif conversation is None:
            logger.info("1-to-1 for user {} is unavailable".format(chat_id))
            return False

        logger.info("sending message to user {} via {}".format(chat_id, conversation.id_))

        yield from self.coro_send_message(conversation, html, context=context)

        return True


    @asyncio.coroutine
    def coro_send_to_user_and_conversation(self, chat_id, conv_id, html_private, html_public=False, context=None):
        """
        If the command was issued on a public channel, respond to the user
        privately and optionally send a short public response back as well.
        """
        conv_1on1_initiator = yield from self.get_1to1(chat_id)

        full_name = _("Unidentified User")
        if self.memory.exists(["user_data", chat_id, "_hangups"]):
            full_name = self.memory["user_data"][chat_id]["_hangups"]["full_name"]

        responses = {
            "standard":
                False, # no public messages
            "optout":
                _("<i>{}, you are currently opted-out. Private message me or enter <b>{} optout</b> to get me to talk to you.</i>")
                    .format(full_name, min(self._handlers.bot_command, key=len)),
            "no1to1":
                _("<i>{}, before I can help you, you need to private message me and say hi.</i>")
                    .format(full_name, min(self._handlers.bot_command, key=len))
        }

        if isinstance(html_public, dict):
            responses = dict
        elif isinstance(html_public, list):
            keys = ["standard", "optout", "no1to1"]
            for supplied in html_public:
                responses[keys.pop(0)] = supplied
        else:
            # isinstance(html_public, str)
            responses["standard"] = html_public

        public_message = False

        if conv_1on1_initiator:
            """always send actual html as a private message"""
            yield from self.coro_send_message(conv_1on1_initiator, html_private)
            if conv_1on1_initiator.id_ != conv_id and responses["standard"]:
                """send a public message, if supplied"""
                public_message = responses["standard"]

        else:
            if type(conv_1on1_initiator) is bool and responses["optout"]:
                public_message = responses["optout"]

            elif responses["no1to1"]:
                # type(conv_1on1_initiator) is NoneType
                public_message = responses["no1to1"]

        if public_message:
            yield from self.coro_send_message(conv_id, public_message, context=context)


    def user_self(self):
        myself = {
            "chat_id": None,
            "full_name": None,
            "email": None
        }
        User = self._user_list._self_user

        myself["chat_id"] = User.id_.chat_id

        if User.full_name: myself["full_name"] = User.full_name
        if User.emails and User.emails[0]: myself["email"] = User.emails[0]

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

    log_level = 'DEBUG' if args.debug else 'INFO'

    default_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'console': {
                'format': '%(asctime)s %(levelname)s %(name)s: %(message)s',
                'datefmt': '%H:%M:%S'
                },
            'default': {
                'format': '%(asctime)s %(levelname)s %(name)s: %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
                }
            },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
                'level': 'INFO',
                'formatter': 'console'
                },
            'file': {
                'class': 'logging.FileHandler',
                'filename': args.log,
                'level': log_level,
                'formatter': 'default',
                }
            },
        'loggers': {
            # root logger
            '': {
                'handlers': ['file', 'console'],
                'level': log_level
                },

            # requests is freakishly noisy
            'requests': { 'level': 'INFO'},

            # XXX: suppress erroneous WARNINGs until resolution of
            #   https://github.com/tdryer/hangups/issues/142
            'hangups': {'level': 'ERROR'},

            # asyncio's debugging logs are VERY noisy, so adjust the log level
            'asyncio': {'level': 'WARNING'},

            # hangups log is verbose too, suppress so we can debug the bot
            'hangups.conversation': {'level': 'ERROR'}
            }
        }

    logging_config = default_config

    # Temporarily bring in the configuration file, just so we can configure
    # logging before bringing anything else up. There is no race internally,
    # if logging() is called before configured, it outputs to stderr, and
    # we will configure it soon enough
    bootcfg = config.Config(args.config)
    if bootcfg.exists(["logging.system"]):
        logging_config = bootcfg["logging.system"]

    if "extras.setattr" in logging_config:
        for class_attr, value in logging_config["extras.setattr"].items():
            try:
                [modulepath, classname, attribute] = class_attr.rsplit(".", maxsplit=2)
                try:
                    setattr(class_from_name(modulepath, classname), attribute, value)
                except ImportError:
                    logging.error("module {} not found".format(modulepath))
                except AttributeError:
                    logging.error("{} in {} not found".format(classname, modulepath))
            except ValueError:
                logging.error("format should be <module>.<class>.<attribute>")

    logging.config.dictConfig(logging_config)

    logger = logging.getLogger()
    if args.debug:
        logger.setLevel(logging.DEBUG)


def main():
    """Main entry point"""
    # Build default paths for files.
    dirs = appdirs.AppDirs('hangupsbot', 'hangupsbot')
    default_log_path = os.path.join(dirs.user_data_dir, 'hangupsbot.log')
    default_cookies_path = os.path.join(dirs.user_data_dir, 'cookies.json')
    default_config_path = os.path.join(dirs.user_data_dir, 'config.json')
    default_memory_path = os.path.join(dirs.user_data_dir, 'memory.json')

    # Configure argument parser
    parser = argparse.ArgumentParser(prog='hangupsbot',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-d', '--debug', action='store_true',
                        help=_('log detailed debugging messages'))
    parser.add_argument('--log', default=default_log_path,
                        help=_('log file path'))
    parser.add_argument('--cookies', default=default_cookies_path,
                        help=_('cookie storage path'))
    parser.add_argument('--memory', default=default_memory_path,
                        help=_('memory storage path'))
    parser.add_argument('--config', default=default_config_path,
                        help=_('config storage path'))
    parser.add_argument('--retries', default=5, type=int,
                        help=_('Maximum disconnect / reconnect retries before quitting'))
    parser.add_argument('--version', action='version', version='%(prog)s {}'.format(version.__version__),
                        help=_('show program\'s version number and exit'))
    args = parser.parse_args()



    # Create all necessary directories.
    for path in [args.log, args.cookies, args.config, args.memory]:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            try:
                os.makedirs(directory)
            except OSError as e:
                sys.exit(_('Failed to create directory: {}').format(e))

    # If there is no config file in user data directory, copy default one there
    if not os.path.isfile(args.config):
        try:
            shutil.copy(os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'config.json')),
                        args.config)
        except (OSError, IOError) as e:
            sys.exit(_('Failed to copy default config file: {}').format(e))

    configure_logging(args)

    # initialise the bot
    bot = HangupsBot(args.cookies, args.config, args.memory, args.retries)

    # start the bot
    bot.run()


if __name__ == '__main__':
    main()
