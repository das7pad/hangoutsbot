"""exceptions for slackrtm"""

class IgnoreMessage(Exception):
    """do not sync a given message"""


class ParseError(Exception):
    """critical slack-message part is missing - api-change"""


class AlreadySyncingError(Exception):
    """attempted to create a duplicate sync"""


class NotSyncingError(Exception):
    """attempted to access/remove a non-existing sync"""


class IncompleteLoginError(Exception):
    """did not receive a full rtm.connect response on login"""


class WebsocketFailed(Exception):
    """can not establish a connection or reading failed permanent"""


class SlackAPIError(Exception):
    """invalid request or missing permissions"""


class SlackRateLimited(SlackAPIError):
    """too many requests performed in a short time span"""


class SlackAuthError(SlackAPIError):
    """error on login"""


class SlackConfigError(SlackAuthError):
    """critical config error: api-key or complete config missing"""
