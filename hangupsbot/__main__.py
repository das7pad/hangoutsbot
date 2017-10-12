"""entrypoint to start the bot"""

import gettext
import os

if __name__ == '__main__':
    # NOTE: bring in localization handling for our own modules
    gettext.install("hangupsbot",
                    localedir=os.path.join(os.path.dirname(__file__),
                                           "locale"))

    from hangupsbot.core import main
    main()
