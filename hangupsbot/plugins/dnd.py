import functools
import logging
import time

import plugins


logger = logging.getLogger(__name__)


def _initialise(bot):
    _reuseable = functools.partial(_user_has_dnd, bot)
    functools.update_wrapper(_reuseable, _user_has_dnd)
    plugins.register_shared('dnd.user_check', _reuseable)
    plugins.register_user_command(["dnd"])


def dnd(bot, event, *args):
    """allow users to toggle DND for ALL conversations (i.e. no @mentions)
        /bot dnd"""

    # ensure dndlist is initialised
    if not bot.memory.exists(["donotdisturb"]):
        bot.memory["donotdisturb"] = {}

    if len(args) == 1 and args[0].isdigit():
        # assume hours supplied
        seconds_to_expire = int(args[0]) * 3600
    else:
        seconds_to_expire = 6 * 3600 # default: 6-hours expiry

    if seconds_to_expire > 259200:
        seconds_to_expire = 259200 # max: 3 days (72 hours)

    initiator_chat_id = event.user.id_.chat_id
    donotdisturb = bot.memory["donotdisturb"]
    if initiator_chat_id in donotdisturb:
        del donotdisturb[initiator_chat_id]
    else:
        donotdisturb[initiator_chat_id] = {
            "created": time.time(),
            "expiry": seconds_to_expire
        }

    bot.memory["donotdisturb"] = donotdisturb
    bot.memory.save()

    if bot.call_shared("dnd.user_check", initiator_chat_id):
        return "global DND toggled ON for {}, expires in {} hour(s)".format(
            event.user.full_name,
            str(seconds_to_expire/3600))
    else:
        return "global DND toggled OFF for {}".format(event.user.full_name)


def _expire_DNDs(bot):
    _dict = {}
    donotdisturb = bot.memory.get("donotdisturb")
    for user_id in donotdisturb:
        metadata = donotdisturb[user_id]
        time_expiry = metadata["created"] + metadata["expiry"]
        if time.time() < time_expiry:
            _dict[user_id] = metadata

    if len(_dict) < len(donotdisturb):
        # some entries expired
        bot.memory.set_by_path(["donotdisturb"], _dict)
        bot.memory.save()


def _user_has_dnd(bot, user_id):
    user_has_dnd = False
    if bot.memory.exists(["donotdisturb"]):
        _expire_DNDs(bot) # expire records prior to check
        donotdisturb = bot.memory.get('donotdisturb')
        if user_id in donotdisturb:
            user_has_dnd = True
    return user_has_dnd
