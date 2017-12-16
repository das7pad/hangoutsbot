"""simple "ask" function for wolfram alpha data

credit goes to @billius for the original plugin

instructions:
* pip3 install wolframalpha
* get API KEY from http://products.wolframalpha.com/developers/
* put API KEY in config.json:wolframalpha-apikey

async rewrite: @das7pad
"""

import logging

import aiohttp
import wolframalpha

from hangupsbot import plugins

logger = logging.getLogger(__name__)

API_URL = "https://api.wolframalpha.com/v2/query"

HELP = {
    'ask': _('solve a question with wolfram alpha'),
}

def _initialise(bot):
    """register the user command"""
    if _api_token(bot):
        plugins.register_user_command(["ask"])
        plugins.register_help(HELP)
    else:
        logger.info('WOLFRAMALPHA: config["wolframalpha-apikey"] required')

def _api_token(bot):
    """get the configured api token

    Args:
        bot (hangupsbot.HangupsBot): the running instance

    Returns:
        str: the configured app id or None if no id is available
    """
    return bot.config.get_option("wolframalpha-apikey")

async def ask(bot, dummy, *args):
    """solve a question with wolfram alpha"""
    result = await _fetch(bot, args)
    return result

async def _fetch(bot, args):
    """fetch data from wolframalpha and parse the response

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        args: tuple of string, query for wolframalpha

    Returns:
        str: the parsed result or an error message
    """
    if not args:
        return _("You need to ask WolframAlpha a question")

    query = ' '.join(args)
    parameters = {'appid': _api_token(bot), 'input': query}

    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL, params=parameters) as resp:
            body = await resp.read()

    result = wolframalpha.Result(body)
    if not result.get('@success'):
        return _('Bad request!')

    if not result.get('pod'):
        return _('Bad response from WolframAlpha, retry or change your query!')

    html = ['WolframAlpha solved the query <b>"{}"</b>\n'.format(query)]

    has_content = False
    try:
        for pod in result.pods:
            if pod.title:
                html.append("<b>{}:</b> ".format(pod.title))

            if pod.text and pod.text.strip():
                html.append(pod.text.strip())
                has_content = True
            elif 'subpod' in pod:
                for subpod in pod.subpods:
                    if 'img' in subpod:
                        html.append(_("%s") % (subpod['img'].get('@src')
                                               or subpod['img'].get('@alt')))
                        has_content = True
    except AttributeError:
        # API Change
        html.append("\n...")

    if has_content:
        return '\n'.join(html)

    return _("<i>Wolfram Alpha did not return any useful data</i>")
