"""datamodels for the hangupsbot"""
__author__ = 'das7pad@outlook.com'

__all__ = (
    'BotMixin',
    'TrackingMixin',
)

_STORAGE = {}


class BotMixin:
    """Mixin which has a `core.HangupsBot` reference during runtime

    The reference is available at `.bot` as an instance attribute only.
    """
    __slots__ = ()
    _STORAGE['bot'] = None

    @property
    def bot(self):
        """get the running HangupsBot

        Returns:
            core.HangupsBot: the running instance
        """
        return _STORAGE['bot']

    @staticmethod
    def set_bot(bot):
        """register the running HangupsBot instance

        Args:
            bot (core.HangupsBot): the running instance
        """
        _STORAGE['bot'] = bot


class TrackingMixin:
    """Mixin which has a `plugins.tracking` reference during runtime

    The reference is available at `.tracking` as an instance attribute only.
    """
    __slots__ = ()
    _STORAGE['tracking'] = None

    @property
    def tracking(self):
        """get the current tracking

        Returns:
            plugins.Tracker: the current instance
        """
        return _STORAGE['tracking']

    @staticmethod
    def set_tracking(tracking):
        """register the plugin tracking

        Args:
            tracking (plugins.Tracker): the current instance
        """
        _STORAGE['tracking'] = tracking
