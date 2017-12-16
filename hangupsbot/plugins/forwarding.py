"""provide one way replays for conversations"""

from hangupsbot import plugins

def _initialise():
    """register the conversation id provider"""
    plugins.register_sync_handler(_get_targets, "conv_sync")

def _get_targets(bot, source_id, caller):
    """get all conversations an event should be relayed to one way

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        source_id (str): source conversation of event
        caller (str): identifier to allow recursive calls

    Returns:
        list: conv_ids of Hangouts which get messages from source_id replayed
    """
    identifier = 'plugins.forwarding'
    if caller == identifier:
        return []
    raw_targets = bot.get_config_suboption(source_id, 'forward_to') or []
    targets = set(raw_targets)
    for target in raw_targets:
        targets.update(bot.sync.get_synced_conversations(conv_id=target,
                                                         caller=identifier))
    targets.discard(source_id)
    return list(targets)
