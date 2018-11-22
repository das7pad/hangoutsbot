"""provide one way replays for conversations"""

from hangupsbot import (
    commands,
    plugins,
)

HELP = {
    'forward_to': _(
        'Add or remove a conversation to/from the targets of the current chat.'
        '\nExample:\n'
        '  {bot_cmd} forward_to tourists'
    ),
}


def _initialise():
    """register the conversation id provider"""
    plugins.register_sync_handler(_get_targets, "conv_sync")
    plugins.register_admin_command([
        'forward_to',
    ])

    plugins.register_help(HELP)


def _get_targets(bot, source_id, caller):
    """get all conversations an event should be relayed to one way

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        source_id (str): source conversation of event
        caller (str): identifier to allow recursive calls

    Returns:
        list[str]: conversation ids which get messages from source_id relayed
    """
    identifier = 'plugins.forwarding'
    if caller == identifier:
        return []
    raw_targets = bot.get_config_suboption(source_id, 'forward_to') or []
    targets = set(raw_targets)
    for target in raw_targets:
        targets.update(
            bot.sync.get_synced_conversations(
                conv_id=target,
                caller=identifier,
            )
        )
    targets.discard(source_id)
    return list(targets)


async def forward_to(bot, event, *args):
    """Add or remove a conversation to/from the targets of the current chat.

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): the aliases/convID to forward to

    Returns:
        str: command output

    Raises:
        commands.Help: missing Alias or ConvID
    """
    if not args:
        raise commands.Help(_('Alias or ConvID missing'))

    status = {}
    src_id = event.conv_id
    config_changed = False

    for conv_id_or_alias in args:
        conv_id = bot.call_shared('alias2convid', conv_id_or_alias)
        if not conv_id:
            conv_id = conv_id_or_alias

        if src_id == conv_id:
            status[conv_id] = -1
            continue

        if conv_id not in bot.conversations:
            status[conv_id] = None
            continue

        path = ['conversations', src_id, 'forward_to']
        if not bot.config.exists(path):
            current = [conv_id]
            status[conv_id] = 0
        else:
            current = bot.config.get_by_path(path)
            if conv_id in current:
                current.remove(conv_id)
                status[conv_id] = 1
            else:
                current.append(conv_id)
                status[conv_id] = 0

        bot.config.set_by_path(path, current)
        config_changed = True

    if config_changed:
        bot.config.save()

    lines = [
        _('Updated the forward targets for these Chats:'),
    ]
    for conv_id, code in status.items():
        if code is None:
            result = _('Unknown chat')
            name = conv_id

        else:
            name = bot.conversations.get_name(conv_id, conv_id)

            if code == -1:
                result = _('Loop blocked')
            elif code == 0:
                result = _('Added')
            else:
                result = _('Removed')

        lines.append('<i>%s</i> : %s' % (name, result))

    return '\n'.join(lines)
