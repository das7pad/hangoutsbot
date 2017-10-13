"""hangupsbot base"""

import gettext
import os

# NOTE: bring in localization handling for our own modules
gettext.install("hangupsbot",
                localedir=os.path.join(os.path.dirname(__file__),
                                       "locale"))
# no public members
__all__ = ()
