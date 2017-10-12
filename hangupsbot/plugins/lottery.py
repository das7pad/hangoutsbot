import logging
import re

from random import shuffle

from commands import Help

import plugins


logger = logging.getLogger(__name__)

HELP = {
    'prepare': _('prepares a bundle of "things" for a random lottery.\n'
                 'parameter: optional "things", draw definitions.\nif "things" '
                 'is not specified, "default" will be used.\ndraw definitions '
                 'can be a simple range such as 1-8; a specific list of things '
                 'to draw such as <i>a,b,c,d,e</i> ; or a shorthand list such '
                 'as <i>2abc1xyz (which prepares list abc,abc,xyz)</i> .\n'
                 'any user can draw once from the default lottery with '
                 'command <i>/me draws</i> .\nif multiple lotteries '
                 '(non-default) are active, the user should use: '
                 '<i>/me draws a "thing"</i> .\nspecial keywords for draw '
                 'definitions: COMPASS creates a list based on the cardinal '
                 'and ordinal directions.'),

    'perform_drawing': _(
        'draw handling:\n<i>/me draw[s] [a[n]] number[s]</i>\n'
        '  draws from "number", "numbers" or "numberes"'
        '<i>/me draw[s] [a[n]] sticks[s]</i>\n'
        '  draws from "stick", "sticks" or "stickses"\n'
        '<i>/me draws[s]<unrecognised></i>\n'
        '  draws from "default"\n\nnote: to prepare lotteries/drawings, see '
        '<b>{bot_cmd} prepare ...</b>'),
}

def _initialise():
    plugins.register_sync_handler(_handle_me_action, "message_once")
    plugins.register_admin_command(["prepare", "perform_drawing"])
    plugins.register_help(HELP)


async def _handle_me_action(bot, event, command):
    # perform a simple check for a recognised pattern (/me draw...)
    #   do more complex checking later
    if event.text.startswith('/me draw') or event.text.startswith(event.user.first_name + ' draw'):
        await command.run(bot, event, *["perform_drawing"])


def _get_global_lottery_name(bot, conversation_id, listname):
    # support for syncrooms plugin
    if bot.config.get_option('syncing_enabled'):
        syncouts = bot.config.get_option('sync_rooms')
        if syncouts:
            for sync_room_list in syncouts:
                # seek the current room, if any
                if conversation_id in sync_room_list:
                    _linked_rooms = sync_room_list
                    _linked_rooms.sort() # keeps the order consistent
                    conversation_id = ":".join(_linked_rooms)
                    logger.debug("joint room keys %s", conversation_id)

    return conversation_id + ":" + listname


def _load_lottery_state(bot):
    draw_lists = {}

    if bot.memory.exists(["lottery"]):
        logger.debug("loading from memory")
        draw_lists = bot.memory["lottery"]

    return draw_lists


def _save_lottery_state(bot, draw_lists):
    bot.memory.set_by_path(["lottery"], draw_lists)
    bot.memory.save()


def prepare(bot, event, *args):
    """prepares a bundle of "things" for a random lottery."""

    max_items = 100

    listname = "default"
    listdef = args[0]
    if len(args) == 2:
        listname = args[0]
        listdef = args[1]
    global_draw_name = _get_global_lottery_name(bot, event.conv.id_, listname)

    draw_lists = _load_lottery_state(bot) # load any existing draws

    draw_lists[global_draw_name] = {"box": [], "users": {}}

    # special types
    #     /bot prepare [thing] COMPASS - 4 cardinal + 4 ordinal
    # XXX: add more useful shortcuts here!
    if listdef == "COMPASS":
        listdef = "north,north-east,east,south-east,south,south-west,west,north-west"

    # parse listdef

    if "," in listdef:
        # comma-separated single tokens
        draw_lists[global_draw_name]["box"] = listdef.split(",")

    elif re.match(r"\d+-\d+", listdef):
        # sequential range: <integer> to <integer>
        _range = listdef.split("-")
        min_ = int(_range[0])
        max_ = int(_range[1])
        if min_ == max_:
            raise Help(_("prepare: min and max are the same ({})").format(min_))
        if max_ < min_:
            min_, max_ = max_, min_
        max_ = max_ + 1 # inclusive
        draw_lists[global_draw_name]["box"] = list(range(min_, max_))

    else:
        # numberTokens: <integer><name>
        pattern = re.compile(r"((\d+)([a-z\-_]+))", re.IGNORECASE)
        matches = pattern.findall(listdef)
        if len(matches) > 1:
            for tokendef in matches:
                tcount = int(tokendef[1])
                tname = tokendef[2]
                for dummy in range(0, tcount):
                    draw_lists[global_draw_name]["box"].append(tname)

        else:
            raise Help(_("prepare: unrecognised match (!csv, !range, !numberToken): {}").format(listdef))

    if len(draw_lists[global_draw_name]["box"]) > max_items:
        del draw_lists[global_draw_name]
        message = _("Wow! Too many items to draw in <b>{}</b> lottery. Try {} items or less...").format(listname, max_items)
    elif draw_lists[global_draw_name]["box"]:
        shuffle(draw_lists[global_draw_name]["box"])
        message = _("The <b>{}</b> lottery is ready: {} items loaded and shuffled into the box.").format(listname, len(draw_lists[global_draw_name]["box"]))
    else:
        raise Help(_("prepare: {} was initialised empty").format(global_draw_name))

    _save_lottery_state(bot, draw_lists) # persist lottery drawings
    return message


def perform_drawing(bot, event, *dummys):
    """draw handling"""
    # XXX: check is for singular, plural "-s" and plural "-es"

    draw_lists = _load_lottery_state(bot) # load in any existing lotteries

    pattern = re.compile(r".+ draws?( +(a +|an +|from +)?([a-z0-9\-_]+))?$", re.IGNORECASE)
    if pattern.match(event.text):
        listname = "default"

        matches = pattern.search(event.text)
        groups = matches.groups()
        if groups[2] is not None:
            listname = groups[2]

        # XXX: TOTALLY WRONG way to handle english plurals!
        # motivation: botmins prepare "THINGS" for a drawing, but users draw a (single) "THING"
        if listname.endswith("s"):
            _plurality = (listname[:-1], listname, listname + "es")
        else:
            _plurality = (listname, listname + "s", listname + "es")
        # seek a matching draw name based on the hacky english singular-plural spellings
        global_draw_name = None
        _test_name = None
        word = None
        for word in _plurality:
            _test_name = _get_global_lottery_name(bot, event.conv.id_, word)
            if _test_name in draw_lists:
                global_draw_name = _test_name
                logger.debug("%s is valid lottery", global_draw_name)
                break

        if global_draw_name is not None:
            if draw_lists[global_draw_name]["box"]:
                if event.user.id_.chat_id in draw_lists[global_draw_name]["users"]:
                    # user already drawn something from the box
                    message = _("<b>{}</b>, you have already drawn <b>{}</b> from the <b>{}</b> box").format(
                        event.user.full_name,
                        draw_lists[global_draw_name]["users"][event.user.id_.chat_id],
                        word)

                else:
                    # draw something for the user
                    _thing = str(draw_lists[global_draw_name]["box"].pop())

                    text_drawn = _("<b>{}</b> draws <b>{}</b> from the <b>{}</b> box. ").format(event.user.full_name, _thing, word, )
                    if not draw_lists[global_draw_name]["box"]:
                        text_drawn = text_drawn + _("...AAAAAND its all gone! The <b>{}</b> lottery is over folks.").format(word)

                    message = text_drawn

                    draw_lists[global_draw_name]["users"][event.user.id_.chat_id] = _thing
            else:
                text_finished = _("<b>{}</b>, the <b>{}</b> lottery is over. ").format(event.user.full_name, word)

                if event.user.id_.chat_id in draw_lists[global_draw_name]["users"]:
                    text_finished = _("You drew a {} previously.").format(draw_lists[global_draw_name]["users"][event.user.id_.chat_id])

                message = text_finished
        else:
            message = None

    _save_lottery_state(bot, draw_lists) # persist lottery drawings
    return message
