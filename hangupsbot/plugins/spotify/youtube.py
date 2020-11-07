import html
import logging
import re

import aiohttp


logger = logging.getLogger(__name__)

_YOUTUBE_META_NAME = re.compile(r'<meta\s+name="title"\s+content="(.+?)">')
_YOUTUBE_TITLE = re.compile(r'<title>([^<]+?) - [^<-]+</title>')

# Regex by mantish from http://stackoverflow.com/a/9102270 to get the
# video id from a YouTube URL.
_YOUTUBE_ID = re.compile(
    r"^.*(youtu.be/|v/|u/\w/|embed/|watch\?v=|&v=)([^#&?]*).*")


def _log_error(url, err):
    if not logger.isEnabledFor(logging.DEBUG):
        logger.info('%s: %s', id(url), url)
    logger.error("%s: %s", id(url), err)


async def get_title_from_youtube(url):
    """get the title of a youtube video

    Args:
        url (str): the video URI

    Returns:
        str: the videos title
    """
    logger.debug('YouTube %s: %s', id(url), url)

    match = _YOUTUBE_ID.match(url)
    if not match or len(match.group(2)) != 11:
        _log_error(url, 'Unable to extract video id')
        return None

    video_id = match.group(2)
    url = 'https://www.youtube.com/watch?v=%s' % video_id

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                blob = await response.text()
    except aiohttp.ClientError as err:
        _log_error(url, err)
        return None

    return _get_title_from_html(url, blob)


def _get_title_from_html(url, blob):
    title = _parse_title_from_html(blob)
    if not title:
        _log_error(url, 'Unable to extract title from web page')
        return None

    return html.unescape(title)


def _parse_title_from_html(blob):
    for title in _YOUTUBE_META_NAME.findall(blob):
        return title

    for title in _YOUTUBE_TITLE.findall(blob):
        return title
