"""bring some random actions to the conversations"""
from random import randint

from commands import Help
import plugins


HELP = {
    "diceroll": _(
        'Rolls dice\nsupply the number and sides of the dice as "<b>n</b>d<b>s'
        '</b>" to roll <b>n</b> dice with <b>s</b> sides\n"d<b>s</b>"'
        "will roll one <b>s</b> sided dice\nno parameters defaults to 1d6\n"
        "e.x. {bot_cmd} diceroll 4d3"),

    "coinflip": _("flip a coin"),
}

def _initialise():
    """register the message handler, commands and the help entrys"""
    plugins.register_sync_handler(_handle_me_action, "message_once")
    plugins.register_user_command(["diceroll", "coinflip"])
    plugins.register_help(HELP)

async def _handle_me_action(bot, event):
    """run the diceroll or coinflip command from context

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
    """
    if not event.text.startswith(('/me', event.user.first_name)):
        return

    if any(item in event.text for item in ["roll dice", "rolls dice",
                                           "rolles a dice", "rolled dice"]):
        await diceroll(bot, event)

    elif any(item in event.text for item in ["flips a coin", "flips coin",
                                             "flip coin", "flipped a coin"]):
        await coinflip(bot, event)

def diceroll(dummy, event, dice="1d6"):
    """get random numbers from a fake diceroll

    Args:
        dummy: HangupsBot instance
        event: event.ConversationEvent instance
        dice: string, the diceroll request
    """
    try:
        repeat, sides = dice.split('d')
    except ValueError:
        sides = None
    if not sides:
        raise Help('Check argument!')
    if not repeat:
        repeat = 1
    repeat = int(repeat)
    sides = int(sides)
    if not 1 <= repeat < 100:
        return _("number of dice must be between 1 and 99")
    if not 2 <= sides < 10000:
        return _("number of sides must be between 2 and 9999")

    msg = _("<i>{} rolled ").format(event.user.full_name)
    numbers = [randint(1, sides) for i in range(repeat)]
    total = sum(numbers)
    msg += "<b>{}</b>".format(", ".join([str(item) for item in numbers]))
    if repeat != 1:
        msg += _(" totalling <b>{}</b></i>").format(total)
    else:
        msg += "</i>"
    return msg

def coinflip(dummy, event, *dummys):
    """get the result of a fake coinflip

    Args:
        dummy: HangupsBot instance
        event: event.ConversationEvent instance
        dummys: tuple of string, not used
    """
    if randint(1, 2) == 1:
        result = _("<i>{}, coin turned up <b>heads</b></i>")
    else:
        result = _("<i>{}, coin turned up <b>tails</b></i>")

    return result.format(event.user.full_name)
