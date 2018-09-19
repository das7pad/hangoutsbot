"""Skip sending into given conversations"""

import logging

from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    'mute': _('Mute a conversation.\n'
              ' {bot_cmd} mute <alias or Chat ID>\n'
              'example: {bot_cmd} mute touri\n'
              'Note: commands and all other message handling will continue to '
              'pick up message from a muted chat.'),
}


def _initialise():
    plugins.register_handler(
        function=_watch_sending,
        pluggable='sending',
        priority=10000  # drop the targets in the very last moment
    )
    plugins.register_user_command(['mute'])
    plugins.register_help(HELP)


async def _watch_sending(bot, targets, context):
    """Drop sending targets that are muted

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        targets (list[tuple[str,str,int]]): a message content wrapper

    Raises:
        SuppressEventHandling: ignore all other handlers
    """
    for target in targets.copy():
        if not bot.memory.exists(['mute', target[0]]):
            continue

        if __name__ in context:
            continue

        logger.debug('%s is muted', target[0])
        targets.remove(target)


async def mute(bot, event, *args):
    """Add or remove a conversation to/from the muted chat list.

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): the aliases to add/remove

    Returns:
        str: command output
    """
    if not args:
        args = (event.conv_id,)

    status = {}
    is_admin = event.user_id.chat_id in bot.config.get_option('admins')
    one_on_one = await bot.get_1to1(event.user_id.chat_id,
                                    force=True)
    if one_on_one:
        conv_id_1on1 = one_on_one.id_
    else:
        conv_id_1on1 = None

    changed_memory = False

    for conv_id_or_alias in args:
        conv_id = bot.call_shared('alias2convid', conv_id_or_alias)
        if not conv_id:
            conv_id = conv_id_or_alias

        if conv_id not in bot.conversations:
            status[conv_id] = None
            continue

        if conv_id != conv_id_1on1 and not is_admin:
            # regular users may only change their private 1on1s setting
            status[conv_id] = -1
            continue

        path = ['mute', conv_id]
        muted = bot.memory.exists(path)
        status[conv_id] = not muted

        if muted:
            bot.memory.pop_by_path(path)
        else:
            bot.memory.set_by_path(path, True)
        changed_memory = True

    if changed_memory:
        bot.memory.save()

    lines = [
        _('Updated the <i>mute</i> setting for these Chats:')
    ]
    for conv_id, code in status.items():
        if code is None:
            result = _('unknown chat')
            name = conv_id

        else:
            name = bot.conversations.get_name(conv_id, conv_id)

            if code == -1:
                result = _('Access denied')
            elif code:
                result = _('enabled mute')
            else:
                result = _('disabled mute')

        lines.append('<i>%s</i> : %s' % (name, result))

    message = '\n'.join(lines)
    context = {
        '__ignore__': True,

        # force sending
        __name__: False,
    }
    return event.conv_id, message, context
