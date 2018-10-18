# TODO(das7pad): needs a refactor


import asyncio
import io
import logging
import os
import re
import sys

import aiohttp

from hangupsbot import plugins


logger = logging.getLogger(__name__)

_EXTERNALS = {"bot": None}


def _initialise(bot):
    _EXTERNALS["bot"] = bot
    plugins.register_shared('image_validate_link', image_validate_link)
    plugins.register_shared('image_upload_single', image_upload_single)
    plugins.register_shared('image_upload_raw', image_upload_raw)
    plugins.register_shared('image_validate_and_upload_single',
                            image_validate_and_upload_single)


def image_validate_link(image_uri, reject_googleusercontent=True):
    """
    validate and possibly mangle supplied image link
    returns False, if not an image link
            <string image uri>
    """

    if " " in image_uri:
        # immediately reject anything with non url-encoded spaces (%20)
        return False

    probable_image_link = False

    image_uri_lower = image_uri.lower()

    if re.match(r"^(https?://)?([a-z0-9.]*?\.)?imgur.com/", image_uri_lower,
                re.IGNORECASE):
        # imgur links can be supplied with/without protocol and extension
        probable_image_link = True

    elif re.match(r'^https?://gfycat.com', image_uri_lower):
        # imgur links can be supplied with/without protocol and extension
        probable_image_link = True

    elif (image_uri_lower.startswith(("http://", "https://", "//")) and
          image_uri_lower.endswith((".png", ".gif", ".gifv", ".jpg", ".jpeg"))):
        # other image links must have protocol and end with valid extension
        probable_image_link = True

    if (probable_image_link and reject_googleusercontent
            and ".googleusercontent." in image_uri_lower):
        # reject links posted by google to prevent endless attachment loop
        logger.debug("rejected link %s with googleusercontent", image_uri)
        return False

    if probable_image_link:

        if "imgur.com" in image_uri:
            if not image_uri.endswith((".jpg", ".gif", "gifv", "webm", "png")):
                image_uri += ".gif"
            image_uri = "https://i.imgur.com/" + os.path.basename(image_uri)

            # imgur wraps animations in player, force the actual image resource
            image_uri = image_uri.replace(".webm", ".gif")
            image_uri = image_uri.replace(".gifv", ".gif")

        elif re.match(r'^https?://gfycat.com', image_uri):
            image_uri = re.sub(r'^https?://gfycat.com/',
                               'https://thumbs.gfycat.com/',
                               image_uri) + '-size_restricted.gif'

        logger.info('%s seems to be a valid image link', image_uri)

        return image_uri

    return False


async def image_upload_single(image_uri):
    filename = os.path.basename(image_uri)
    logger.info("fetching %s", filename)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request('get', image_uri) as res:
                content_type = res.headers['Content-Type']

                # must be True if valid image, can contain additional directives
                image_handling = False

                # image handling logic for specific image types
                #  - if necessary, guess by extension

                if content_type.startswith('image/'):
                    if content_type == "image/webp":
                        image_handling = "image_convert_to_png"
                    else:
                        image_handling = "standard"

                elif content_type == "application/octet-stream":
                    # guess the type from the extension
                    ext = filename.split(".")[-1].lower()

                    if (ext in
                            ("jpg", "jpeg", "jpe", "jif", "jfif", "gif", "png")):
                        image_handling = "standard"
                    elif ext == "webp":
                        image_handling = "image_convert_to_png"

                if image_handling:
                    raw = await res.read()
                    if image_handling != "standard":
                        try:
                            results = await getattr(sys.modules[__name__],
                                                    image_handling)(raw)
                            if results:
                                # allow custom handlers to fail gracefully
                                raw = results
                        except Exception:  # pylint: disable=broad-except
                            # unhandled Exception from custom image handler
                            logger.exception("custom image handler failed: %s",
                                             image_handling)
                else:
                    logger.warning(
                        "not image/image-like, filename=%s, headers=%s",
                        filename, res.headers)
                    return False

    except aiohttp.ClientError as exc:
        logger.warning("failed to get %r - %r", filename, exc)
        return False

    image_data = io.BytesIO(raw)
    image_id = await image_upload_raw(image_data, filename=filename)
    return image_id


async def image_upload_raw(image_data, filename):
    image_id = False
    try:
        image_id = await _EXTERNALS["bot"].upload_image(image_data,
                                                        filename=filename)
    except KeyError as exc:
        logger.warning("upload_image failed: %r", exc)
    return image_id


async def image_validate_and_upload_single(text, reject_googleusercontent=True):
    # pylint:disable=invalid-name
    image_id = False
    image_link = image_validate_link(
        image_uri=text, reject_googleusercontent=reject_googleusercontent)
    if image_link:
        image_id = await image_upload_single(image_link)
    return image_id


async def image_convert_to_png(image):
    path_imagemagick = _EXTERNALS["bot"].config.get_option(
        "image.imagemagick") or "/usr/bin/convert"
    cmd = (path_imagemagick, "-", "png:-")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        (stdout_data, dummy) = await process.communicate(input=image)

        return stdout_data

    except FileNotFoundError:
        logger.warning("imagemagick not found at path %s", path_imagemagick)
        return False
