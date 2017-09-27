"""subscribe to phrases and get mentioned about them in attending chats"""

import asyncio
import logging
import re

import commands
import plugins

logger = logging.getLogger(__name__)

USER_NOTE_SELF_MENTION = _(
    "Note: You will not be able to trigger your own subscriptions. To test, "
    "please ask somebody else to test this for you."
    )
USER_NOTE_START_1ON1 = _(
    "Note: I am unable to ping you until you start a 1on1 conversation with me!"
    )

# Cache to keep track of what keywords are being watched.
# _keywords is indexed with a users chat_id, _global_keywords by keyword
_keywords = {}
_global_keywords = {}

MENTION_TEMPLATE = (
    '<b>{name}</b> mentioned "<b>%s</b>" in <i>%s</i> :\n{edited}{text}')

IGNORED_COMMANDS = set((
    'subscribe',
    'unsubscribe',
    'global_subscribe',
    'global_unsubscribe',
))

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
    bot.register_shared('hide_from_subscribe', _hide_from_subscribe)
    bot.config.set_defaults({"subscribe.enabled": True})
    bot.memory.set_defaults({"hosubscribe": {}})
    bot.memory.ensure_path(["user_data"])
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

def _populate_keywords(bot):
    """Pull the keywords from memory

    Args:
        bot: HangupsBot instance
    """
    for userchatid in bot.memory.get_option("user_data"):
        userkeywords = bot.user_memory_get(userchatid, "keywords")
        if userkeywords is not None:
            _keywords[userchatid] = userkeywords
    _global_keywords.update(bot.memory['hosubscribe'])

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
    for user in users_in_chat:
        chat_id = user.id_.chat_id
        if (not include_event_user and
                chat_id in event.notified_users):
            # user is part of event or already got mentioned for this event
            continue
        user_phrases = _keywords.get(chat_id, [])
        matches = []
        for phrase in user_phrases:
            if phrase in event_text:
                matches.append(phrase)

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
    previous_targets = event.previous_targets.union(event.targets)

    for keyword, conversations in _global_keywords.copy().items():
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
    raw_text = event.get_formated_text(template='{text}', style='internal')

    highlighted = raw_text
    for phrase in matches:
        highlighted = highlighted.replace(phrase, '<b>%s</b>' % phrase)

    text = event.get_formated_text(template=template, names_text_only=True,
                                   text=highlighted)

    await bot.coro_send_message(conv_1on1, text)
    logger.info("%s (%s) alerted via 1on1 (%s)",
                user.full_name, user.id_.chat_id, conv_1on1.id_)

async def subscribe(bot, event, *args):
    """allow users to subscribe to phrases, only one input at a time

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        *args: tuple of strings, additional words as the keyword to subscribe
    """
    keyword = ' '.join(args).lower()
    chat_id = event.user_id.chat_id

    conv_1on1 = await bot.get_1to1(chat_id)
    if not conv_1on1:
        await bot.coro_send_message(event.conv_id, USER_NOTE_START_1ON1)

    lines = []
    if keyword:
        if chat_id in _keywords:
            if keyword in _keywords[chat_id]:
                # Duplicate!
                return _("Already subscribed to '{}'!").format(keyword)
            else:
                # Not a duplicate, proceeding
                _keywords[chat_id].append(keyword)
        else:
            # first one ever
            _keywords[chat_id] = [keyword]
            lines.append(USER_NOTE_SELF_MENTION)

        # Save to file
        bot.user_memory_set(chat_id, "keywords", _keywords[chat_id])

    else:
        # user might need help
        lines.append(_("Usage: {bot_cmd} subscribe [keyword]").format(
            bot_cmd=bot.command_prefix))

    if _keywords[chat_id]:
        # Note: print each keyword into one line to differeniate between
        # "'keyword1', 'keyword2'" and "'keyword1, keyword1', 'keyword2'"
        # second happens as users try to add more than one keyword at once
        lines.append(_("Subscribed to:"))
        lines += _keywords[chat_id]

    return '\n'.join(lines)

def unsubscribe(bot, event, *args):
    """Allow users to unsubscribe from phrases

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        *args: tuple of strings, additional words as the keyword to unsubscribe
    """
    chat_id = event.user_id.chat_id

    if chat_id not in _keywords:
        return _('No subscribes found for you')

    keyword = ' '.join(args).lower()
    if not keyword:
        text = _("Unsubscribing all keywords")
        _keywords[chat_id] = []

    elif keyword in _keywords[chat_id]:
        text = _("Unsubscribing from keyword '{}'").format(keyword)
        _keywords[chat_id].remove(keyword)

    else:
        return _('keyword "%s" not found') % keyword

    bot.user_memory_set(chat_id, "keywords", _keywords[chat_id])
    return text

def testsubscribe(bot, event, *dummys):
    """handle the event text and allow the user to be self-mentioned

    Args:
        bot: HangupsBot instance
        event: event.ChatMessageEvent instance
        *args: list of strings, additional words as the test mention
    """
    _handle_keyword(bot, event, False, include_event_user=True)

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

    if keyword in _global_keywords:
        if alias in _global_keywords[keyword]:
            return _('The conversation "%s" already receives messages '
                     'containing "%s".') % (alias, keyword)

        _global_keywords[keyword].append(alias)
        text = _('These conversation will receive messages containing "%s":'
                 '\n%s') % (keyword, ', '.join(_global_keywords[keyword]))

    elif keyword != 'show':
        _global_keywords[keyword] = [alias]
        text = _('The conversation "%s" is the only one with a subscribe to '
                 '"%s"') % (alias, keyword)

    else:
        subscribes = []
        for keyword_, conversations in _global_keywords.copy().items():
            if alias in conversations:
                subscribes.append(keyword_)
        return _('The conversation "%s" has subscribed to %s') % (
            alias, (', '.join(['"%s"' % item for item in subscribes])
                    or _('None')))

    bot.memory['hosubscribe'] = _global_keywords
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

    if keyword not in _global_keywords:
        return _('No conversation has subscribed to %s') % keyword

    if alias not in _global_keywords[keyword]:
        return _('The conversation "%s" has not subscribed to "%s"') % (alias,
                                                                        keyword)

    _global_keywords[keyword].remove(alias)

    if not _global_keywords[keyword]:
        # cleanup
        _global_keywords.pop(keyword)

    bot.memory['hosubscribe'] = _global_keywords
    bot.memory.save()
    return _('The conversation "%s" will no longer receive messages '
             'containing "%s"') % (alias, keyword)
