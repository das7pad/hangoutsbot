"""exceptions for telesync"""


class IgnoreMessage(Exception):
    """message content should not be synced"""


class NotSupportedMessageType(Exception):
    """Message type is not supported"""
