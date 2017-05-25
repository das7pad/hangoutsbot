"""example plugin demonstrating various levels of sending handler suppression"""
from exceptions import HangupsBotExceptions
import plugins

def _initialise():
    """register a handler for a given pluggable"""
    plugins.register_handler(_shutup, "sending", priority=49)

def _shutup(bot, event, command):
    """suppress registered handler to work entirely above the configured level

    Args:
        bot: HangupsBot instance
        event: ConversationEvent instance
        command: command handler from commands

    Raises:
        the uncommented handler suppressor
    """
    # suppresses this specific handler only
    # raise HangupsBotExceptions.SuppressHandler

    # disables all handlers of priority > 49
    # raise HangupsBotExceptions.SuppressAllHandlers

    # disables sending entirely
    raise HangupsBotExceptions.SuppressEventHandling
