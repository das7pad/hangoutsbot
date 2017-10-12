"""merge multiple hangouts into a sync room"""

from hangupsbot import plugins

def _initialise():
    """register conv sync provider"""
    plugins.register_sync_handler(_get_targets, "conv_sync")

def _get_targets(bot, source_id, caller):
    """get all conversations an event should be relayed to

    Args:
        bot: HangupsBot instance
        source_id: string, source conversation of event
        caller: string, identifier to allow recursive calls

    Returns:
        list with conversation ids that are in a syncroom with that source_id
    """
    identifier = 'plugins.syncrooms'
    if caller == identifier:
        return []

    if not bot.config.get_option('syncing_enabled'):
        return []

    syncouts = bot.config.get_option('sync_rooms')
    if not syncouts:
        return []

    raw_targets = set()
    for sync_room_list in syncouts:
        if source_id in sync_room_list:
            raw_targets.update(sync_room_list)

    raw_targets.discard(source_id)

    targets = set(raw_targets)
    for target in raw_targets:
        targets.update(bot.sync.get_synced_conversations(conv_id=target,
                                                         caller=identifier))
    targets.discard(source_id)
    return list(targets)
