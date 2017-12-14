"""subscribe to phrases and get mentioned about them in attending chats"""

import asyncio
import logging
import re

from hangupsbot import commands
from hangupsbot import plugins
from hangupsbot.sync.event import SyncEvent

logger = logging.getLogger(__name__)

USER_NOTE_SELF_MENTION = _(
    "Note: You will not be able to trigger your own subscriptions. To test, "
    "please ask somebody else to test this for you."
    )
USER_NOTE_START_1ON1 = _(
    "Note: I am unable to ping you until you start a 1on1 conversation with me!"
    )

# Cache to keep track of what keywords are being watched.
# _KEYWORDS is indexed with a users chat_id, _GLOBAL_KEYWORDS by keyword
_KEYWORDS = {}
_GLOBAL_KEYWORDS = {}

MENTION_TEMPLATE = (
    '<b>{name}</b> mentioned "<b>%s</b>" in <i>%s</i> :\n{edited}{text}')

IGNORED_COMMANDS = set((
    'subscribe',
    'unsubscribe',
    'global_subscribe',
    'global_unsubscribe',
))

HELP = {
    'subscribe': _('allow users to subscribe to phrases, only one input at a '
                   'time\n'
                   'example: {bot_cmd} subscribe Downtime'),

    'unsubscribe': _('Allow users to unsubscribe from phrases'),

    'testsubscribe': _('handle the event text and allow the user to be '
                       'self-mentioned'),

    'global_subscribe': ('subscribe keywords globally with a custom '
                         'conversation as target\n'
                         'use <i>{bot_cmd} global_subscribe [conv] show</i> to '
                         'list all keywords that redirect messages into the '
                         'current or given conversation\n'
                         'example: {bot_cmd} global_subscribe #audit'),

    'global_unsubscribe': _('unsubscribe from keywords globally\n'
                            'example: {bot_cmd} global_unsubscribe #audit'),
}
_DEFAULT_CONFIG = {
    'subscribe.enabled': True,
}
_DEFAULT_MEMORY = {
    'subscribe': {
        '_migrated_': 0,
    },
    'user_data': {},
    'hosubscribe': {},
}
_RE_UNESCAPE = re.compile(r'\\()')

def _initialise(bot):
    """start listening to messages, register commands and cache user keywords

    Args:
        bot: HangupsBot instance
    """
    plugins.register_sync_handler(_handle_keyword, 'message')
    plugins.register_sync_handler(_handle_once, 'message_once')
    plugins.register_user_command(["subscribe", "unsubscribe"])
    plugins.register_admin_command(["global_subscribe", "global_unsubscribe"])
    plugins.register_admin_command(["testsubscribe"])
    plugins.register_help(HELP)
    bot.register_shared('hide_from_subscribe', _hide_from_subscribe)

    bot.config.set_defaults(_DEFAULT_CONFIG)
    bot.memory.validate(_DEFAULT_MEMORY)
    _migrate_data(bot)
    bot.memory.save()

    _populate_keywords(bot)

def _hide_from_subscribe(item):
    """register a command to be hidden from subscribes on execute

    Args:
        item: string or tuple or list, a single or multiple commands
    """
    if isinstance(item, str):
        IGNORED_COMMANDS.add(item)
    elif isinstance(item, (list, tuple)):
        IGNORED_COMMANDS.update(item)
    else:
        logger.warning('%s is not a valid command container', repr(item),
                       include_stack=True)

def _migrate_data(bot):
    """escape keywords

    Args:
        bot (HangupsBot): the running instance
    """
    path = ['subscribe', '_migrated_']
    if bot.memory.get_by_path(path) < 20171029:
        # escape keywords
        for data in bot.memory['user_data'].values():
            if 'keywords' not in data:
                continue
            data['keywords'] = [re.escape(entry) for entry in data['keywords']]
        bot.memory.set_by_path(path, 20171029)

def _populate_keywords(bot):
    """Pull the keywords from memory

    Args:
        bot: HangupsBot instance
    """
    for user_chat_id in bot.memory.get_option("user_data"):
        user_keywords = bot.user_memory_get(user_chat_id, 'keywords')
        if user_keywords:
            _KEYWORDS[user_chat_id] = re.compile(r'|'.join(user_keywords))
    _GLOBAL_KEYWORDS.update(bot.memory['hosubscribe'])

def _is_ignored_command(event):
    """check whether the event runs a command that should not trigger a mention

    Args:
        event: sync.event.SyncEvent instance

    Returns:
        boolean
    """
    args = event.text.split()
    if len(args) < 2:
        return False
    prefixes = event.bot._handlers.bot_command # pylint:disable=protected-access
    return args[0] in prefixes and args[1] in IGNORED_COMMANDS

def _handle_keyword(bot, event, dummy, include_event_user=False):
    """handle keyword"""
    if _is_ignored_command(event):
        return

    users_in_chat = event.user_list
    if not bot.get_config_suboption(event.conv_id, 'subscribe.enabled'):
        return

    event_text = re.sub(r"\s+", " ", event.text).lower()
    if event.conv_event.attachments:
        event_text.replace(event.conv_event.attachments[0], '').strip('\n')
    for user in users_in_chat:
        chat_id = user.id_.chat_id
        if (not include_event_user and
                chat_id in event.notified_users):
            # user is part of event or already got mentioned for this event
            continue
        if chat_id not in _KEYWORDS:
            continue
        user_phrases = _KEYWORDS[chat_id]
        matches = set(user_phrases.findall(event_text))

        if not matches:
            continue
        event.notified_users.add(user.id_.chat_id)
        asyncio.ensure_future(
            _send_notification(bot, event, matches, user))

def _handle_once(bot, event):
    """scan the text of an event for subscribed keywords and notify the targets

    Args:
        bot: HangupsBot instance
        event: sync.event.SyncEvent instance
    """
    # ignore marked HOs
    if any(bot.get_config_suboption(conv_id, 'ignore_hosubscribe')
           for conv_id in event.targets):
        return

    if _is_ignored_command(event):
        return

    matches = {}
    event_text = event.text.lower()
    if event.conv_event.attachments:
        event_text.replace(event.conv_event.attachments[0], '').strip('\n')
    previous_targets = event.previous_targets.union(event.targets)

    for keyword, conversations in _GLOBAL_KEYWORDS.copy().items():
        if keyword not in event_text:
            continue
        for alias in conversations:
            conv_id = bot.call_shared('alias2convid', alias) or alias

            if 'hangouts:' + conv_id in previous_targets:
                # received the message already
                continue
            matches[conv_id] = keyword

    user = bot.sync.get_sync_user(user_id=bot.user_self()['chat_id'])
    kwargs = dict(identifier='hangouts:%s' % event.conv_id, user=user, title='',
                  notified_users=event.notified_users,
                  previous_targets=previous_targets)
    for conv_id, keyword in matches.items():
        user_name = event.user.get_displayname(conv_id, text_only=True)
        title = event.title(conv_id)
        if title:
            title = ' in <i>%s</i> ' % title
        text = _('<b>{}</b> mentioned "{}"{}:\n{}').format(
            user_name, keyword, title, event.text)
        asyncio.ensure_future(bot.sync.message(conv_id=conv_id, text=text,
                                               **kwargs))

async def _send_notification(bot, event, matches, user):
    """Alert a user that a keyword that they subscribed to has been used

    Args:
        bot: HangupsBot instance
        event: sync.event.SyncEvent instance
        matches: list of strings, keywords that were found in the message
        user: sync.user.SyncUser instance, user who subscribe to the phrase
    """
    logger.info("keywords %s in '%s' (%s)",
                matches, event.title(), event.conv_id)

    conv_1on1 = await bot.get_1to1(
        user.id_.chat_id, context={'initiator_convid': event.conv_id})
    if not conv_1on1:
        logger.warning("user %s (%s) could not be alerted via 1on1",
                       user.full_name, user.id_.chat_id)
        return

    try:
        user_has_dnd = bot.call_shared("dnd.user_check", user.id_.chat_id)
    except KeyError:
        user_has_dnd = False

    if user_has_dnd:
        logger.info("%s (%s) has dnd", user.full_name, user.id_.chat_id)
        return

    phrases = '</b>", "<b>'.join(matches)
    template = MENTION_TEMPLATE % (phrases, event.display_title)
    raw_text = event.get_formatted_text(template='{text}', style='internal')

    highlighted = raw_text
    for phrase in matches:
        highlighted = highlighted.replace(phrase, '<b>%s</b>' % phrase)

    text = event.get_formatted_text(template=template, names_text_only=True,
                                    text=highlighted)

    await bot.coro_send_message(conv_1on1, text)
    logger.info("%s (%s) alerted via 1on1 (%s)",
                user.full_name, user.id_.chat_id, conv_1on1.id_)

def _unescape_regex(regex):
    """replace escaped regex char

    Args:
        regex (str): escaped regex string

    Returns:
        str: unescaped source
    """
    return _RE_UNESCAPE.sub(r'\1', regex.replace(r'\b', ' '))

def _escape_keyword(keyword):
    """escape a keyword to use it as part of a regex

    Args:
        keyword (str): user input

    Returns:
        str: re escaped input
    """
    if (len(keyword) > 2
            and keyword[1] == keyword[-2] == ' '
            and keyword[0] == keyword[-1]
            and keyword[0] in '"\''):
        return r'\b%s\b' % re.escape(keyword[2:-2])
    return re.escape(keyword)

async def subscribe(bot, event, *args):
    """allow users to subscribe to phrases, only one input at a time

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        *args: tuple of strings, additional words as the keyword to subscribe
    """
    keyword = ' '.join(args).lower()
    regex = _escape_keyword(keyword)

    chat_id = event.user_id.chat_id
    user_keywords = bot.user_memory_get(chat_id, 'keywords')

    conv_1on1 = await bot.get_1to1(chat_id)
    if not conv_1on1:
        await bot.coro_send_message(event.conv_id, USER_NOTE_START_1ON1)

    lines = []
    if keyword:
        if user_keywords is None:
            # first one ever
            user_keywords = []
            lines.append(USER_NOTE_SELF_MENTION)
            lines.append('')

        elif regex in user_keywords:
            # Duplicate!
            return _("Already subscribed to '{}'!").format(keyword)

        user_keywords.append(regex)
        _KEYWORDS[chat_id] = re.compile(r'|'.join(user_keywords))

        # Save to file
        bot.user_memory_set(chat_id, 'keywords', user_keywords)

    else:
        # user might need help
        lines.append(_("Usage: {bot_cmd} subscribe [keyword]").format(
            bot_cmd=bot.command_prefix))

    if user_keywords:
        # Note: print each keyword into one line to differentiate between
        # "'keyword1', 'keyword2'" and "'keyword1, keyword1', 'keyword2'"
        # second happens as users try to add more than one keyword at once
        lines.append(_("Subscribed to:"))
        lines += [repr(_unescape_regex(entry)) for entry in user_keywords]

    return '\n'.join(lines)

def unsubscribe(bot, event, *args):
    """Allow users to unsubscribe from phrases

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        *args: tuple of strings, additional words as the keyword to unsubscribe
    """
    chat_id = event.user_id.chat_id
    user_keywords = bot.user_memory_get(chat_id, 'keywords')

    if not user_keywords:
        return _('No subscribes found for you')

    keyword = ' '.join(args).lower()
    regex = _escape_keyword(keyword)

    if not keyword:
        lines = [_("Unsubscribing all keywords:")]
        lines += [repr(_unescape_regex(entry)) for entry in user_keywords]
        text = '\n'.join(lines)
        _KEYWORDS.pop(chat_id)
        user_keywords = []

    elif regex in user_keywords:
        text = _("Unsubscribing from keyword '{}'").format(keyword)
        user_keywords.remove(regex)
        if user_keywords:
            _KEYWORDS[chat_id] = re.compile(r'|'.join(user_keywords))
        else:
            _KEYWORDS.pop(chat_id)

    else:
        return _('keyword "%s" not found') % keyword

    bot.user_memory_set(chat_id, 'keywords', user_keywords)
    return text

async def testsubscribe(bot, event, *dummys):
    """handle the event text and allow the user to be self-mentioned

    Args:
        bot: HangupsBot instance
        event: event.ChatMessageEvent instance
        *args: list of strings, additional words as the test mention
    """
    sync_event = SyncEvent(conv_id=event.conv_id, user=event.user_id,
                           text=event.conv_event.segments)
    await sync_event.process()
    _handle_keyword(bot, sync_event, False, include_event_user=True)

def global_subscribe(bot, event, *args):
    """subscribe keywords globally with a custom conversation as target

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple, additional strings passed to the command

    Returns:
        string
    """
    if not args:
        raise commands.Help('Missing keyword and/or conversation!')

    if len(args) == 2 and (bot.call_shared('alias2convid', args[0]) or
                           args[0] in bot.conversations):
        conv_id = bot.call_shared('alias2convid', args[0]) or args[0]
    else:
        conv_id = event.conv_id

    alias = bot.call_shared('convid2alias', conv_id) or conv_id
    keyword = args[-1].lower()

    if keyword in _GLOBAL_KEYWORDS:
        if alias in _GLOBAL_KEYWORDS[keyword]:
            return _('The conversation "{alias}" already receives messages '
                     'containing "{keyword}".').format(alias=alias,
                                                       keyword=keyword)

        _GLOBAL_KEYWORDS[keyword].append(alias)
        text = _('These conversation will receive messages containing '
                 '"{keyword}":\n{conv_ids}').format(
                     keyword=keyword,
                     conv_ids=', '.join(_GLOBAL_KEYWORDS[keyword]))

    elif keyword != 'show':
        _GLOBAL_KEYWORDS[keyword] = [alias]
        text = _('The conversation "{alias}" is the only one with a subscribe '
                 'on "{keyword}"').format(alias=alias, keyword=keyword)

    else:
        subscribes = []
        for keyword_, conversations in _GLOBAL_KEYWORDS.copy().items():
            if alias in conversations:
                subscribes.append(keyword_)
        return _('The conversation "{alias}" has subscribed to {keywords}'
                ).format(
                    alias=alias,
                    keywords=(', '.join('"%s"' % item for item in subscribes)
                              or _('None')))

    bot.memory['hosubscribe'] = _GLOBAL_KEYWORDS
    bot.memory.save()
    return text

def global_unsubscribe(bot, event, *args):
    """unsubscribe from keywords globally

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple, additional strings passed to the command

    Returns:
        string
    """
    if not args:
        raise commands.Help('Missing keyword and/or conversation!')

    if len(args) == 2 and (bot.call_shared('alias2convid', args[0]) or
                           args[0] in bot.conversations):
        conv_id = bot.call_shared('alias2convid', args[0]) or args[0]
    else:
        conv_id = event.conv_id

    alias = bot.call_shared('convid2alias', conv_id) or conv_id
    keyword = args[-1].lower()

    if keyword not in _GLOBAL_KEYWORDS:
        return _('No conversation has subscribed to %s') % keyword

    if alias not in _GLOBAL_KEYWORDS[keyword]:
        return _('The conversation "{alias}" has not subscribed to "{keyword}"'
                ).format(alias=alias, keyword=keyword)

    _GLOBAL_KEYWORDS[keyword].remove(alias)

    if not _GLOBAL_KEYWORDS[keyword]:
        # cleanup
        _GLOBAL_KEYWORDS.pop(keyword)

    bot.memory['hosubscribe'] = _GLOBAL_KEYWORDS
    bot.memory.save()
    return _('The conversation "{alias}" will no longer receive messages '
             'containing "{keyword}"').format(alias=alias, keyword=keyword)
