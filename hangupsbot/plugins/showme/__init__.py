"""the "showme" function retrieves image snapshots and sends them to the user.

a source for snapshots can be either security cameras or other URL's accessible
to the hangupsbot server

Config must specify aliases and urls which should include any nessisary auth.
"""
__LICENSE__ = """
The BSD License
Copyright (c) 2015, Daniel Casner
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
__author__ = "Daniel Casner <www.artificelab.com>"

import io
import logging
import time
import aiohttp
import hangups
from hangupsbot import plugins

logger = logging.getLogger(__name__)

HELP = {
    'showme': _('Retrieve images from showme sources by saying:\n'
                ' {bot_cmd} showme SOURCE\n'
                'list sources by saying:\n'
                ' {bot_cmd} showme sources\n'
                'or all sources by saying\n'
                ' {bot_cmd} showme all'),
}

def _initalize(bot):
    """register the showme command if sources are configured in config

    Args:
        bot: HangupsBot instance
    """
    if bot.config.get_option("showme") is not None:
        plugins.register_user_command(["showme"])
        plugins.register_help(HELP, "showme")
    else:
        logger.info('SHOWME: config["showme"] dict required')

async def _send_source(bot, event, name, img_link):
    """fetch the provided source and reupload the image and send a message

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        name: string, source label
        img_link: string, url to a shared webcam
    """
    logger.info("Getting %s", img_link)
    async with aiohttp.ClientSession() as session:
        async with session.request("get", img_link) as res:
            raw = await res.read()
    content_type = res.headers['Content-Type']
    logger.info("\tContent-type: %s", content_type)
    ext = content_type.split('/')[1]
    image_data = io.BytesIO(raw)
    filename = "{}_{}.{}".format(name, int(time.time()), ext)
    try:
        image_id = await bot.upload_image(image_data, filename=filename)
    except hangups.NetworkError:
        await bot.coro_send_message(
            event.conv_id,
            _("I'm sorry, I couldn't upload a {} image".format(ext)))
    else:
        await bot.coro_send_message(event.conv.id_, None, image_id=image_id)

async def showme(bot, event, *args):
    """retrieve images from web cameras

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple of strings, words passed to the command,
            see HELP for details

    Returns:
        string, user output; or None if a valid image request was made
    """
    sources = bot.config.get_option("showme")
    if not args:
        return _("Show you what?")
    elif args[0].lower() == 'sources':
        html = """My sources are:\n"""
        for name in sources.keys():
            html += " * {}\n".format(name)
        return _(html)
    elif args[0].lower() == 'all':
        for name, source in sources.items():
            await _send_source(bot, event, name, source)
    elif not args[0] in sources:
        return _("I don't know a \"{}\", try sources".format(args[0]))
    else:
        await _send_source(bot, event, args[0], sources[args[0]])
