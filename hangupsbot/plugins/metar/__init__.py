"""
Looks up the most recent METAR/TAF weather report for the supplied ICAO airport code.
        <b>/bot metar <ICAO airport code></b>
        <b>/bot taf <ICAO airport code></b>

ICAO Airport Codes: https://en.wikipedia.org/wiki/International_Civil_Aviation_Organization_airport_code
METAR source: http://aviationweather.gov
"""

import logging
from xml.etree import ElementTree

import aiohttp

from hangupsbot import plugins

logger = logging.getLogger(__name__)

HELP = {
    'metar': _('Display the current METAR weather report for the supplied '
               'ICAO airport code.\n'
               ' <b>{bot_cmd} metar <ICAO airport code></b>\n'
               'ICAO Airport Codes: https://en.wikipedia.org/wiki/International'
               '_Civil_Aviation_Organization_airport_code\n'
               'METAR source: http://aviationweather.gov'),

    'taf': _('Looks up the most recent TAF weather forecast for the supplied '
             'ICAO airport code.\n'
             ' <b>{bot_cmd} taf <ICAO airport code></b>\n'
             'ICAO Airport Codes: https://en.wikipedia.org/wiki/International_'
             'Civil_Aviation_Organization_airport_code\n'
             'TAF source: http://aviationweather.gov'),
}

def _initialize():
    plugins.register_user_command(['metar', 'taf'])
    plugins.register_help(HELP)

async def _api_lookup(target, station):
    api_url = "http://aviationweather.gov/adds/dataserver_current/httpparam?dataSource={0}s&requestType=retrieve&format=xml&hoursBeforeNow=3&mostRecent=true&stationString={1}".format(target, station)
    response = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                response.raise_for_status()
                raw_text = await response.text()
        root = ElementTree.fromstring(raw_text)
        raw = root.findall('data/{}/raw_text'.format(target))
    except ElementTree.ParseError as err:
        logger.info("METAR Error: %s, raw_data: %s", err, repr(raw_text))
        return None
    except aiohttp.ClientError:
        logger.info("METAR Error: %s", repr(response))
        return None
    return raw

async def metar(dummy0, dummy1, *args):
    """Display the current METAR weather report for the supplied ICAO airport"""
    code = ''.join(args).strip()
    if not code:
        return _("You need to enter the ICAO airport code you wish the look up,"
                 "https://en.wikipedia.org/wiki/International_Civil_Aviation_Organization_airport_code")

    data = await _api_lookup('METAR', code)

    if data is None:
        return _("There was an error retrieving the METAR information.")
    elif not data:
        return _("The response did not contain METAR information, check the "
                 "ICAO airport code and try again.")
    return data[0].text

async def taf(dummy0, dummy1, *args):
    """Looks up the most recent TAF weather forecast for the supplied airport"""

    code = ''.join(args).strip()
    if not code:
        return _("You need to enter the ICAO airport code you wish the look up,"
                 " https://en.wikipedia.org/wiki/International_Civil_Aviation_Organization_airport_code")

    data = await _api_lookup('TAF', code)

    if data is None:
        return _("There was an error retrieving the TAF information.")
    elif not data:
        return _("The response did not contain TAF information, check the "
                 "ICAO airport code and try again.")
    return data[0].text
