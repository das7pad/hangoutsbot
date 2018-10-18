"""Exceptions that can be raised in the sync module"""

from hangupsbot import utils


class MissingArgument(ValueError):
    """argument is missing"""


class UnRegisteredProfilesync(KeyError):
    """SyncHandler.start_profile_sync called before .register_profile_sync"""


class ProfilesyncAlreadyCompleted(utils.FormatBaseException):
    """The user has completed his profilesync already"""


class HandlerFailed(RuntimeError):
    """a handler raised an Exception"""
