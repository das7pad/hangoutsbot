import logging

import aiohttp

from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    'catfact': _('get catfacts'),
}


def _initialise():
    plugins.register_user_command([
        "catfact",
    ])
    plugins.register_help(HELP)


async def catfact(dummy0, dummy1, *args):
    number = args[0] if args and args[0].isdigit() else 1
    url = "https://catfact.ninja/facts?limit={}".format(number)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                raw = await response.json()
                facts = [fact['fact'] for fact in raw['data']]
    except (aiohttp.ClientError, KeyError):
        text = "Unable to get catfacts right now"
        logger.exception(url)
        return text
    else:
        return '<br>'.join(facts)
