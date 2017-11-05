import asyncio
import io
import logging
import os
import re
import time
import tempfile

import hangups
import selenium
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    'screenshot': _('get a screenshot of a user provided URL or the default URL'
                    ' of the hangout.'),

    'seturl': _('set url for current converation for the screenshot command.\n'
                '  use <b>{bot_cmd} clearurl</b> to clear the previous url '
                'before setting a new one.'),

    'clearurl': _('clear the default-url for current converation for the '
                  'screenshot command.'),
}

_EXTERNALS = {"running": False}


_DCAP = dict(DesiredCapabilities.PHANTOMJS)
_DCAP["phantomjs.page.settings.userAgent"] = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/534.34  "
    "(KHTML, like Gecko) PhantomJS/1.9.7 Safari/534.34"
)


def _initialise():
    plugins.register_user_command(["screenshot"])
    plugins.register_admin_command(["seturl", "clearurl"])
    plugins.register_help(HELP)


async def _open_file(name):
    logger.debug("opening screenshot file: %s", name)
    return open(name, 'rb')


async def _screencap(browser, url, filename):
    logger.info("screencapping %s and saving as %s", url, filename)
    browser.set_window_size(1280, 800)
    browser.get(url)
    await asyncio.sleep(5)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, browser.save_screenshot, filename)

    # read the resulting file into a byte array
    file_resource = await _open_file(filename)
    file_data = await loop.run_in_executor(None, file_resource.read)
    file_resource.close()
    image_data = await loop.run_in_executor(None, io.BytesIO, file_data)
    await loop.run_in_executor(None, os.remove, filename)

    return image_data


def seturl(bot, event, *args):
    """set url for current converation for the screenshot command."""
    url = bot.conversation_memory_get(event.conv_id, 'url')
    if url is None:
        bot.conversation_memory_set(event.conv_id, 'url', ''.join(args))
        html = "<i><b>%s</b> updated screenshot URL" % event.user.full_name

    else:
        html = (_("<i><b>{}</b> URL already exists for this conversation!\n\n")
                .format(event.user.full_name))
        html += "<i>Clear it first with /bot clearurl before setting a new one."

    return html


def clearurl(bot, event, *dummys):
    """clear url for current converation for the screenshot command."""
    url = bot.conversation_memory_get(event.conv_id, 'url')
    if url is None:
        html = _("<i><b>{}</b> nothing to clear for this conversation")

    else:
        bot.conversation_memory_set(event.conv_id, 'url', None)
        html = _("<i><b>{}</b> URL cleared for this conversation!\n")

    return html.format(event.user.full_name)

async def screenshot(bot, event, *args):
    """get a screenshot of a user provided URL or the hangouts' default URL"""
    if _EXTERNALS["running"]:
        return "<i>processing another request, try again shortly</i>"

    if args:
        url = args[0]
    else:
        url = bot.conversation_memory_get(event.conv_id, 'url')

    if url is None:
        html = _("<i><b>{}</b> No URL has been set for screenshots and none was"
                 " provided manually.").format(event.user.full_name)
        return html

    else:
        _EXTERNALS["running"] = True

        if not re.match(r'^[a-zA-Z]+://', url):
            url = 'http://' + url
        filename = event.conv_id + "." + str(time.time()) +".png"
        filepath = tempfile.NamedTemporaryFile(prefix=event.conv_id,
                                               suffix=".png", delete=False).name
        logger.debug("temporary screenshot file: %s", filepath)

        try:
            browser = webdriver.PhantomJS(desired_capabilities=_DCAP,
                                          service_log_path=os.path.devnull)
        except selenium.common.exceptions.WebDriverException:
            _EXTERNALS["running"] = False
            return "<i>phantomjs could not be started - is it installed?</i>"

        try:
            image_data = await _screencap(browser, url, filepath)
        except selenium.common.exceptions.WebDriverException:
            logger.exception("screencap failed %s", url)
            _EXTERNALS["running"] = False
            return "<i>error getting screenshot</i>"

        try:
            try:
                image_id = await bot.call_shared('image_upload_raw', image_data,
                                                 filename=filename)
            except KeyError:
                logger.info('image plugin not loaded - using legacy code')
                image_id = await bot.upload_image(image_data,
                                                  filename=filename)
            await bot.coro_send_message(event.conv_id, url, image_id=image_id)
        except hangups.NetworkError:
            logger.exception("upload failed %s", url)
            return "<i>error uploading screenshot</i>"
        finally:
            _EXTERNALS["running"] = False
