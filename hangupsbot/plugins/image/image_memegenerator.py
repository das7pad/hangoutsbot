import logging
import os
import random

import aiohttp
import hangups

from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    'meme': _('Searches for a meme related to <something>.\n'
              'grabs a random meme when none provided'),
}

_EXTERNALS = {"running": False}


def _initialise():
    plugins.register_user_command(["meme"])
    plugins.register_help(HELP)


async def meme(bot, event, *args):
    """Searches for a meme related to <something>"""
    if _EXTERNALS["running"]:
        await bot.coro_send_message(event.conv_id, "<i>busy, give me a moment...</i>")
        return

    _EXTERNALS["running"] = True

    try:
        parameters = args or ("robot",)

        # public api: http://version1.api.memegenerator.net
        url_api = 'http://version1.api.memegenerator.net/Instances_Search?q=' + "+".join(parameters) + '&pageIndex=0&pageSize=25'

        async with aiohttp.ClientSession() as session:
            async with session.request('get', url_api) as api_request:
                results = await api_request.json()

        if results['result']:
            url_image = random.choice(results['result'])['instanceImageUrl']

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url_image) as response:
                        response.raise_for_status()
                        image_data = await response.read()
            except aiohttp.ClientError:
                logger.error('url: %s, response: %s', url_image, repr(response))
                raise

            filename = os.path.basename(url_image)
            segments = [hangups.ChatMessageSegment(
                url_image, hangups.hangouts_pb2.SEGMENT_TYPE_LINK,
                link_target=url_image)]
            logger.debug("uploading %s from %s", filename, url_image)

            try:
                photo_id = await bot.call_shared('image_upload_single', url_image)
            except KeyError:
                logger.warning('image plugin not loaded - using legacy code')
                photo_id = await bot.upload_image(image_data, filename=filename)

            await bot.coro_send_message(event.conv_id, segments, image_id=photo_id)

        else:
            await bot.coro_send_message(event.conv_id, "<i>couldn't find a nice picture :( try again</i>")

    except (aiohttp.ClientError, KeyError, IndexError, hangups.NetworkError):
        await bot.coro_send_message(event.conv_id, "<i>couldn't find a suitable meme! try again</i>")
        logger.exception("FAILED TO RETRIEVE MEME: %s", repr(parameters))

    finally:
        _EXTERNALS["running"] = False
