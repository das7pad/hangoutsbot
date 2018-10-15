import logging
import urllib.parse

import aiohttp

from hangupsbot import plugins
from hangupsbot.commands import Help

logger = logging.getLogger(__name__)

HELP = {
    'foursquareid': _('Set the Foursquare API key for the bot\n'
                      '  Get one from https://foursquare.com/oauth'),

    'foursquaresecret': _('Set the Foursquare client secret for your bot\n'
                          '  Get it from https://foursquare.com/oauth'),

    'foursquare': _('Explore places near you with Foursquare!\n'
                    ' <b>{bot_cmd} foursquare <location></b>:\n'
                    '   Display up to 10 of the recommended places near the '
                    'specified location.\n'
                    ' <b>{bot_cmd} foursquare [type] <location></b>:\n'
                    'Display up to 10 places near the provided location of the '
                    'type specified.\n'
                    '<i>Valid types: food, drinks, coffee, shops, arts, '
                    'outdoors, sights, trending, specials</i>'),
}

def _initialise():
    plugins.register_admin_command(["foursquareid", "foursquaresecret"])
    plugins.register_user_command(['foursquare'])
    plugins.register_help(HELP)

def foursquareid(bot, dummy, *args):
    """Set the Foursquare API key for the bot"""
    if not args:
        raise Help()
    client_id = args[0]

    if not bot.memory.exists(["foursquare"]):
        bot.memory.set_by_path(["foursquare"], {})

    if not bot.memory.exists(["foursquare"]):
        bot.memory.set_by_path(["foursquare", "id"], {})

    bot.memory.set_by_path(["foursquare", "id"], client_id)
    return "Foursquare client id set to {}".format(client_id)

def foursquaresecret(bot, dummy, *args):
    """Set the Foursquare client secret for your bot"""
    if not args:
        raise Help()
    secret = args[0]

    if not bot.memory.exists(["foursquare"]):
        bot.memory.set_by_path(["foursquare"], {})

    if not bot.memory.exists(["foursquare"]):
        bot.memory.set_by_path(["foursquare", "secret"], {})

    bot.memory.set_by_path(["foursquare", "secret"], secret)
    return "Foursquare client secret set to {}".format(secret)

async def get_places(location, client_id, secret, section=None):
    url = "https://api.foursquare.com/v2/venues/explore?client_id={}&client_secret={}&limit=10&v=20160503&near={}".format(client_id, secret, location)
    types = ["food", "drinks", "coffee", "shops", "arts", "outdoors", "sights", "trending", "specials"]
    if section in types:
        url += "&section={}".format(section)
    elif section is None:
        pass
    else:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
    except aiohttp.ClientError as err:
        logger.info('get_places %s: %r', id(err), location)
        logger.error('get_places %s: failed: %r', id(err), err)
        return "<i><b>Foursquare Error</b></i>"

    if section in types:
        places = ["Showing {} places near {}.<br>".format(section, data['response']['geocode']['displayString'])]
    else:
        places = ["Showing places near {}.<br>".format(data['response']['geocode']['displayString'])]
    for item in data['response']['groups'][0]['items']:
        maps_url = "http://maps.google.com/maps?q={}, {}".format(item['venue']['location']['lat'], item['venue']['location']['lng'])
        places.append("<b><u><a href='{}'>{}</a></b></u> (<a href='{}'>maps</a>)<br>Score: {}/10 ({})".format(maps_url, item['venue']["name"], "http://foursquare.com/v/{}".format(item['venue']['id']), item['venue']['rating'], item['venue']['ratingSignals']))

    response = "<br>".join(places)
    return response


async def foursquare(bot, dummy, *args):
    """Explore places near you with Foursquare!"""
    if not args:
        raise Help()

    try:
        client_id = bot.memory.get_by_path(["foursquare", "id"])
        secret = bot.memory.get_by_path(["foursquare", "secret"])
    except (KeyError, TypeError):
        return _("Something went wrong - make sure the Foursquare plugin is correctly configured.")

    types = ["food", "drinks", "coffee", "shops", "arts", "outdoors", "sights", "trending", "specials"]
    if args[0] in types:
        places = await get_places(urllib.parse.quote(" ".join(args[1:])), client_id, secret, args[0])
    else:
        places = await get_places(urllib.parse.quote(" ".join(args)), client_id, secret)

    if places:
        return places
    return _("Something went wrong.")
