"""fixtures for testing"""

__all__ = (
    'bot',
    'event',
    'module_wrapper',
)

import asyncio
import copy
import logging
import time

import hangups
import hangups.http_utils
import hangups.user
import pytest
from hangups import hangouts_pb2
from hangups.conversation_event import (
    ChatMessageEvent,
    ChatMessageSegment,
)

import hangupsbot.commands
import hangupsbot.core
import hangupsbot.handlers
import hangupsbot.permamem
import hangupsbot.plugins
import hangupsbot.sinks
import hangupsbot.sync.handler
import hangupsbot.tagging
from hangupsbot.event import ConversationEvent
from hangupsbot.hangups_conversation import HangupsConversationList
from tests.constants import (
    CHAT_ID_1,
    CHAT_ID_2,
    CONFIG_DATA,
    CONFIG_DATA_DUMPED,
    CONV_ID_1,
    CONV_ID_2,
    DEFAULT_BOT_KWARGS,
    DEFAULT_TIMESTAMP,
    EVENT_LOOP,
    PYTHON36,
)
from tests.utils import (
    Message,
    build_user_conversation_list_base,
)


USER_LIST_KWARGS, CONV_LIST_KWARGS = build_user_conversation_list_base()
CLEANUP_LOOP = asyncio.new_event_loop()
logger = logging.getLogger('tests')


@pytest.fixture
def event_loop(request):
    """Fixture for the current event loop.

    Patch for pytest-asyncio, which creates a new instance for every function.
    """
    yield asyncio.get_event_loop()


@pytest.fixture(scope='module', autouse=True)
def module_wrapper(request):
    def _cleanup():
        CLEANUP_LOOP.run_until_complete(hangupsbot.commands.command.clear())
        CLEANUP_LOOP.run_until_complete(hangupsbot.plugins.tracking.clear())
        CLEANUP_LOOP.run_until_complete(
            hangupsbot.sinks.aiohttp_servers.clear())
        hangupsbot.core.AsyncQueue.release_block()
        if PYTHON36:
            CLEANUP_LOOP.run_until_complete(EVENT_LOOP.shutdown_asyncgens())
        EVENT_LOOP.run_until_complete(asyncio.sleep(0.1))

    request.addfinalizer(_cleanup)
    logger.info('Loaded Module %s', request.module.__name__)


class TestChatMessageEvent(ChatMessageEvent):
    """Low level `hangups.conversation_event.ConversationEvent`

    Args:
        conv_id (str): conversation identifier
        chat_id (str): G+ user identifier
        text (str): raw_text that may contain markdown or html formatting
        segments (iterable): a list/tuple of `ChatMessageSegment`s

    Raises:
        ValueError: invalid content provided
    """

    def __init__(self, conv_id, chat_id, text=None, segments=None):
        if isinstance(text, str):
            segments = ChatMessageSegment.from_str(text)
        try:
            raw_segments = (seg.serialize() for seg in segments)
        except (TypeError, AttributeError):
            raise ValueError('invalid text provided') from None
        super().__init__(hangouts_pb2.Event(
            conversation_id=hangouts_pb2.ConversationId(
                id=conv_id),
            sender_id=hangouts_pb2.ParticipantId(
                chat_id=chat_id,
                gaia_id=chat_id),
            timestamp=DEFAULT_TIMESTAMP,
            chat_message=hangouts_pb2.ChatMessage(
                message_content=hangouts_pb2.MessageContent(
                    segment=raw_segments),
            ),
            event_id='EVENT_ID-%s' % time.time(),
            event_type=hangouts_pb2.EVENT_TYPE_REGULAR_CHAT_MESSAGE))


class TestConversationEvent(ConversationEvent):
    """High level `hangupsbot.event.ConversationEvent`

    Args:
        conv_id (str): conversation identifier
        chat_id (str): G+ user identifier
        text (str): raw_text that may contain markdown or html formatting
        segments (iterable): a list/tuple of `ChatMessageSegment`s

    Raises:
        ValueError: invalid content provided
    """

    def __init__(self, conv_id, chat_id, text=None, segments=()):
        conv_event = TestChatMessageEvent(conv_id, chat_id, text, segments)
        super().__init__(conv_event)
        self.CONV_ID = conv_id
        self.CHAT_ID = chat_id

    def with_text(self, text=None, segments=None):
        """get an event with the given text

        Args:
            text (str): raw_text that may contain markdown or html formatting
            segments (iterable): a list/tuple of `ChatMessageSegment`s

        Returns:
            TestConversationEvent: a new event with the given text

        Raises:
            ValueError: invalid content provided
        """
        return TestConversationEvent(self.CONV_ID, self.CHAT_ID, text, segments)

    def for_command(self, cmd, *args):
        """get an event with the given command name and args

        Args:
            cmd (str): the command name
            args (str): the command args

        Returns:
            TestConversationEvent: a new event with the given args

        Raises:
            ValueError: invalid content provided
        """
        # allow calls `.for_command('CMD', 'my args')` and
        # `.for_command('CMD', 'my', 'args')`
        args = args[0].split() if args and ' ' in args[0] else args

        text = ' '.join(args)
        return self.with_text('/bot %s %s' % (cmd, text))

    @property
    def args(self):
        return self.text.split()[2:]


@pytest.fixture(params=((CONV_ID_1, CHAT_ID_1),
                        (CONV_ID_1, CHAT_ID_2),
                        (CONV_ID_2, CHAT_ID_1),
                        (CONV_ID_2, CHAT_ID_2)))
def event(request):
    conv_id, chat_id = request.param
    return TestConversationEvent(conv_id, chat_id)


class TestHangupsBot(hangupsbot.core.HangupsBot):
    def __init__(self):
        # pylint:disable=protected-access
        super().__init__(**DEFAULT_BOT_KWARGS)
        # clear config and memory
        self.config.config = copy.deepcopy(CONFIG_DATA)
        self.config._last_dump = CONFIG_DATA_DUMPED
        self.config.defaults = {}
        self.memory.config = {}
        self.memory._last_dump = ''
        self.memory.defaults = {}

        self._message_queue = []

        # patch .run()
        self._client = hangups.Client({'SAPISID': 'IS_REQUIRED'})

        # patch ._on_connect()
        self.shared = {}
        self.tags = hangupsbot.tagging.Tags()
        self._handlers = hangupsbot.handlers.EventHandler()
        self.sync = hangupsbot.sync.handler.SyncHandler(self._handlers)
        self._user_list = hangups.UserList(self._client, **USER_LIST_KWARGS)
        self._conv_list = HangupsConversationList(
            self._client, user_list=self._user_list, **CONV_LIST_KWARGS)

        EVENT_LOOP.run_until_complete(self._handlers.setup(self._conv_list))
        EVENT_LOOP.run_until_complete(self.sync.setup())
        EVENT_LOOP.run_until_complete(hangupsbot.permamem.initialise(self))

    async def coro_send_message(self, conversation, message, context=None,
                                image_id=None):
        self._message_queue.append(
            Message(conversation, message, context, image_id))

    @property
    def last_message(self):
        """get schedules messages

        Returns:
            tests.utils.Message: a queued message
        """
        return self._message_queue[-1]


@pytest.fixture(scope='module')
def bot():
    """get a fresh TestHangupsBot instance per module"""
    return TestHangupsBot()
