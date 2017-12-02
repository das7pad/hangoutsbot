"""datamodels for the hangupsbot"""
__author__ = 'das7pad@outlook.com'

__all__ = (
    'BotMixin',
)

class BotMixin:
    """Mixin which has a `core.HangupsBot` reference during runtime"""
    bot = None

    @classmethod
    def set_bot(cls, bot):
        """register the running HangupsBot instance

        Args:
            bot (core.HangupsBot): the running instance
        """
        cls.bot = bot
