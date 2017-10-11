# vim: set ts=4 expandtab sw=4

import io
import json
import os.path
import re
import urllib.parse

import aiohttp
from hangups import ChatMessageSegment

import plugins

_cache = {}

def _initialise():
    plugins.register_user_command(["xkcd"])
    plugins.register_help(HELP)
    plugins.register_sync_handler(_watch_xkcd_link, "message_once")

regexps = (
    r"https?://(?:www\.)?(?:explain)?xkcd.com/([0-9]+)(?:/|\s|$)",
    r"https?://(?:www\.)?explainxkcd.com/wiki/index\.php(?:/|\?title=)([0-9]+)(?:[^0-9]|$)",
    r"(?:\s|^)xkcd\s+(?:#\s*)?([0-9]+)(?:\s|$)",
)

HELP = {
    'xkcd': _('show latest comic\n'
              '  {bot_cmd} xkcd latest\n'
              '  {bot_cmd} xkcd current\n'
              'clear comic cache\n'
              '  {bot_cmd} xkcd clear\n'
              'search for a comic\n'
              '  {bot_cmd} xkcd search <query>'),
}

async def xkcd(bot, event, *args):
    """xkcd interface"""
    if len(args) == 1:
        if args[0] == "clear":
            _cache.clear()
            return

        if args[0] == "search":
            await _search_comic(bot, event, args[1:])
            return

        if args[0] in ("latest", "current"):
            # ignore
            return

    await _print_comic(bot, event)

async def _watch_xkcd_link(bot, event):
    # Don't handle events caused by the bot himself
    if event.user.is_self:
        return

    for regexp in regexps:
        match = re.search(regexp, event.text, flags=re.IGNORECASE)
        if not match:
            continue

        num = match.group(1)
        await _print_comic(bot, event, num)
        return # only one match per message

async def _get_comic(bot, num=None):
    if num:
        num = int(num)
        url = 'https://xkcd.com/%d/info.0.json' % num
    else:
        num = None
        url = 'https://xkcd.com/info.0.json'

    if num in _cache:
        return _cache[num]
    else:
        async with aiohttp.ClientSession() as session:
            async with session.request('get', url) as request:
                raw = await request.read()
        info = json.loads(raw.decode())

        if info['num'] in _cache:
            # may happen when searching for the latest comic
            return _cache[info['num']]

        filename = os.path.basename(info["img"])
        async with aiohttp.ClientSession() as session:
            async with session.request('get', info["img"]) as request:
                raw = await request.read()
        image_data = io.BytesIO(raw)
        info['image_id'] = await bot.upload_image(image_data, filename=filename)
        _cache[info['num']] = info
        return info

async def _print_comic(bot, event, num=None):
    info = await _get_comic(bot, num)
    image_id = info['image_id']

    context = {
        "parser": False,
    }

    msg1 = [
        ChatMessageSegment("xkcd #%s: " % info['num']),
        ChatMessageSegment(info["title"], is_bold=True),
    ]
    msg2 = [
        ChatMessageSegment(info["alt"]),
    ] + ChatMessageSegment.from_str('\n- <i><a href="https://xkcd.com/%s">CC-BY-SA xkcd</a></i>' % info['num'])
    if "link" in info and info["link"]:
        msg2.extend(ChatMessageSegment.from_str("\n* see also %s" % info["link"]))

    await bot.coro_send_message(event.conv.id_, msg1, context)
    await bot.coro_send_message(event.conv.id_, msg2, context, image_id=image_id) # image appears above text, so order is [msg1, image, msg2]

async def _search_comic(bot, event, terms):
    url = ("https://relevantxkcd.appspot.com/process?%s"
           % urllib.parse.urlencode({"action": "xkcd",
                                     "query": " ".join(terms)}))
    async with aiohttp.ClientSession() as session:
        async with session.request('get', url) as request:
            raw = await request.read()
    values = [row.strip().split(" ")[0] for row in raw.decode().strip().split("\n")]

    weight = float(values.pop(0))
    values.pop(0) # selection - ignore?
    comics = [int(i) for i in values]
    num = comics.pop(0)

    msg = 'Most relevant xkcd: #%d (relevance: %.2f%%)\nOther relevant comics: %s' % (num, weight*100, ", ".join("#%d" % i for i in comics))

    # get info and upload image if necessary
    await _get_comic(bot, num)

    await bot.coro_send_message(event.conv.id_, msg)
    await _print_comic(bot, event, num)
