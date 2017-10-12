"""
cleverbot hangoutsbot plugin
requires: https://pypi.python.org/pypi/cleverwrap
commands: chat, chatreset

configuration
-------------

set the cleverbot API key by saying:

/bot config set cleverbot_api_key "<API KEY>"

read more (and register) on the cleverbot API here:
    https://www.cleverbot.com/api/

config.json
-----------
* cleverbot_api_key
  * string cleverbot api key
* cleverbot_percentage_replies
  * integer between 0-100 for % chance of replying to a user message
* cleverbot_segregate
  * UNSET/True to keep cleverbot memory separate in each conversation
  * False to share memory between conversations
"""

import plugins
import logging

from random import randrange

logger = logging.getLogger(__name__)

try:
    from cleverwrap import CleverWrap
except ImportError:
    logger.warning("required module: cleverwrap")
    raise

__cleverbots = {}

HELP = {
    'chat': _('chat with cleverbot\n\nexample: {bot_cmd} chat hi cleverbot!'),
    'chatreset': _("tells cleverbot to forget things you've said in the past"),
}

def _initialise():
    plugins.register_sync_handler(_handle_incoming_message, "message_once")
    plugins.register_user_command(["chat"])
    plugins.register_admin_command(["chatreset"])
    plugins.register_help(HELP)


async def _handle_incoming_message(bot, event):
    """setting a global or per-conv cleverbot_percentage_replies config key
    will make this plugin intercept random messages to be sent to cleverbot"""

    if not event.text:
        return

    if not bot.get_config_suboption(event.conv_id, 'cleverbot_percentage_replies'):
        return

    percentage = bot.get_config_suboption(event.conv_id, 'cleverbot_percentage_replies')

    if randrange(0, 101, 1) < float(percentage):
        await chat(bot, event)


def _get_cw_for_chat(bot, event):
    """initialise/get cleverbot api wrapper"""

    # setting segregate to False makes cleverbot share its memory across non-segregated conversations
    # important: be careful of information leaking from one conversation to another!
    # by default, conversation memory is segregrated by instantiating new cleverwrap interfaces
    segregate = bot.get_config_suboption(event.conv_id, "cleverbot_segregate")
    if segregate is None:
        segregate = True
    if segregate:
        index = event.conv_id
    else:
        index = "shared"

    if index in __cleverbots:
        return __cleverbots[index]

    # dev: you can define different API keys for different conversations
    api_key = bot.get_config_suboption(event.conv_id, "cleverbot_api_key")
    if not api_key:
        return None
    cw = CleverWrap(api_key)
    __cleverbots[index] = cw
    logger.debug("created new cw for %s", index)
    return cw


def chat(bot, event, *args):
    """chat with cleverbot"""

    cw = _get_cw_for_chat(bot, event)
    if not cw:
        response = "API key not defined: config.cleverbot_api_key"
        logger.error(response)
        return response

    if args:
        input_text = " ".join(args)
    else:
        input_text = event.text

    # cw.say takes one argument, the input string. It is a blocking call that returns cleverbot's response.
    # see https://github.com/edwardslabs/cleverwrap.py for more information
    response = cw.say(input_text)

    return response


def chatreset(bot, event, *dummys):
    """tells cleverbot to forget things you've said in the past"""

    cw = _get_cw_for_chat(bot, event)
    if cw:
        cw.reset()
    return "cleverbot has been reset!"
