"""example plugin demonstrating various levels of sending handler suppression"""

from hangupsbot import plugins
from hangupsbot.exceptions import HangupsBotExceptions


def _initialise():
    """register a handler for a given pluggable"""
    plugins.register_handler(_shutup, "sending", priority=49)


def _shutup():
    """suppress registered handler to work entirely above the configured level

    Raises:
        HangupsBotExceptions.SuppressEventHandling: discard the event
    """
    # suppresses this specific handler only
    # raise HangupsBotExceptions.SuppressHandler

    # disables all handlers of priority > 49
    # raise HangupsBotExceptions.SuppressAllHandlers

    # disables sending entirely
    raise HangupsBotExceptions.SuppressEventHandling
