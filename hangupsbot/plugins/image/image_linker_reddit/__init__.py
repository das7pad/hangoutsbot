"""trigger popular reddit meme images
based on the word/image list for the image linker bot on reddit
sauce: http://www.reddit.com/r/image_linker_bot/comments/2znbrg/image_suggestion_thread_20/
"""
import asyncio
import aiohttp, io, logging, os, random, re

import plugins


logger = logging.getLogger(__name__)


_lookup = {}


def _initialise(bot):
    _load_all_the_things()
    plugins.register_admin_command(["redditmemeword"])
    plugins.register_handler(_scan_for_triggers)


def redditmemeword(bot, event, *args):
    """trigger popular reddit meme images (eg. type 'slowclap.gif').
    Full list at http://goo.gl/ORmisN"""
    if len(args) == 1:
        image_link = _get_a_link(args[0])
        return "this one? {}".format(image_link)


async def _scan_for_triggers(bot, event, command):
    limit = 3
    count = 0
    lctext = event.text.lower()
    image_links = []
    for trigger in _lookup:
        pattern = '\\b' + trigger + '\.(jpg|png|gif|bmp)\\b'
        if re.search(pattern, lctext):
            image_links.append(_get_a_link(trigger))
            count = count + 1
            if count >= limit:
                break

    image_links = list(set(image_links)) # make unique

    if image_links:
        for image_link in image_links:
            try:
                image_id = await bot.call_shared('image_validate_and_upload_single', image_link)
            except KeyError:
                logger.warning('image plugin not loaded - using legacy code')
                if re.match(r'^https?://gfycat.com', image_link):
                    image_link = re.sub(r'^https?://gfycat.com/', 'https://thumbs.gfycat.com/', image_link) + '-size_restricted.gif'
                elif "imgur.com" in image_link:
                    image_link = image_link.replace(".gifv",".gif")
                    image_link = image_link.replace(".webm",".gif")
                filename = os.path.basename(image_link)
                r = await aiohttp.request('get', image_link)
                raw = await r.read()
                image_data = io.BytesIO(raw)
                logger.debug("uploading: {}".format(filename))
                image_id = await bot._client.upload_image(image_data, filename=filename)
            await bot.coro_send_message(event.conv.id_, "", image_id=image_id)


def _load_all_the_things():
    plugin_dir = os.path.dirname(os.path.realpath(__file__))
    source_file = os.path.join(plugin_dir, "sauce.txt")
    with open(source_file) as f:
        content = f.read().splitlines()
    for line in content:
        parts = line.strip("|").split('|')
        if len(parts) == 2:
            triggers, images = parts
            triggers = [x.strip() for x in triggers.split(',')]
            images = [re.search('\((.*?)\)$', x).group(1) for x in images.split(' ')]
            for trigger in triggers:
                if trigger in _lookup:
                    _lookup[trigger].extend(images)
                else:
                    _lookup[trigger] = images
    logger.debug("{} trigger(s) loaded".format(len(_lookup)))


def _get_a_link(trigger):
    if trigger in _lookup:
        return random.choice(_lookup[trigger])
    return False
