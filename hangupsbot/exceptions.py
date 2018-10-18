"""Exceptions used for the HangupsBot core"""


class SuppressHandler(Exception):
    """suppress a single handler"""


class SuppressAllHandlers(Exception):
    """suppress all handler on a single pluggable level"""


class SuppressEventHandling(Exception):
    """suppress any further handling of an event"""


class HangupsBotExceptions:
    """Exceptions used for event handler suppressing"""
    # pylint: disable=too-few-public-methods

    SuppressHandler = SuppressHandler
    SuppressAllHandlers = SuppressAllHandlers
    SuppressEventHandling = SuppressEventHandling
