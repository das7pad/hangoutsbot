"""Simple interface to urbandictionary.com

Author: Roman Bogorodskiy <bogorodskiy@gmail.com>
"""
import logging
from html.parser import HTMLParser
from urllib.parse import quote as urlquote

import aiohttp

from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    'urbandict': _('lookup a term on Urban Dictionary. supplying no parameters '
                   'will get you a random term.\n'
                   'DISCLAIMER: all definitions are from '
                   'http://www.urbandictionary.com/\n'
                   '- the bot and its creators/maintainers take no '
                   'responsibility for any hurt feelings.'),
}


class UrbanDictParser(HTMLParser):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._section = None
        self.translations = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if not tag in ("div", "a"):
            return

        div_class = attrs_dict.get('class')
        if div_class in ('word', 'meaning', 'example'):
            self._section = div_class
            if div_class == 'word':  # NOTE: assume 'word' is the first section
                self.translations.append(
                    {'word': '', 'def': '', 'example': ''})

    def handle_endtag(self, tag):
        if tag == 'div':
            # NOTE: assume there is no nested <div> in the known sections
            self._section = None

    def handle_data(self, data):
        if not self._section:
            return

        if self._section == 'meaning':
            self._section = 'def'
        elif self._section == 'word':
            data = data.strip()

        self.translations[-1][self._section] += normalize_newlines(data)

    def error(self, message):
        logger.error('parse error: %r', message)


def normalize_newlines(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


async def urbandict(dummy0, dummy1, *args):
    """lookup a term on Urban Dictionary."""

    term = " ".join(args)
    if not term:
        url = "http://www.urbandictionary.com/random.php"
    else:
        url = "http://www.urbandictionary.com/define.php?term=" + urlquote(term)

    logger.debug('api call %s: url %r', id(url), url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.text()
    except aiohttp.ClientError as err:
        if not logger.isEnabledFor(logging.DEBUG):
            # add context
            logger.info('api call %s: url %r', id(url), url)

        logger.error('api call %s: failed %r', id(url), err)
        return _('urbandict: request failed :(')

    logger.debug('api call %s: data %r', id(url), data)

    urbandict_parser = UrbanDictParser()
    try:
        urbandict_parser.feed(data)
    except IndexError:
        # apparently, nothing was returned
        pass

    if urbandict_parser.translations:
        html_text = ""
        the_definition = urbandict_parser.translations[0]
        html_text += '<b>"' + the_definition["word"] + '"</b>\n\n'
        if "def" in the_definition:
            html_text += _("<b>definition:</b> ")
            html_text += the_definition["def"].strip()
            html_text += '\n\n'
        if "example" in the_definition:
            html_text += _("<b>example:</b> ")
            html_text += the_definition["example"].strip()

        return html_text

    if term:
        return _('<i>no urban dictionary definition for "{}"</i>').format(
            term)
    return _('<i>no term from urban dictionary</i>')


def _initialise():
    plugins.register_user_command([
        "urbandict",
    ])
    plugins.register_help(HELP)
