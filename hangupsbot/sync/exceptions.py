"""Exceptions that can be raised in the sync module"""

class MissingArgument(ValueError):
    """argument is missing"""

class UnRegisteredProfilesync(KeyError):
    """SyncHandler.start_profile_sync called before .register_profile_sync"""
