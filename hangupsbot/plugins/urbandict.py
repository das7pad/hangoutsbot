"""Simple interface to urbandictionary.com

Author: Roman Bogorodskiy <bogorodskiy@gmail.com>
"""
#TODO(das7pad) move to aiohttp for the requests

import logging
from urllib.request import urlopen
from urllib.parse import quote as urlquote
from html.parser import HTMLParser

import plugins

logger = logging.getLogger(__name__)

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
            #NOTE: assume there is no nested <div> in the known sections
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
        logger.error(message)

def normalize_newlines(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def urbandict(bot, event, *args):
    """lookup a term on Urban Dictionary.
    supplying no parameters will get you a random term.
    DISCLAIMER: all definitions are from http://www.urbandictionary.com/ - the bot and its
    creators/maintainers take no responsibility for any hurt feelings.
    """

    term = " ".join(args)
    if not term:
        url = "http://www.urbandictionary.com/random.php"
    else:
        url = "http://www.urbandictionary.com/define.php?term=" + urlquote(term)

    f = urlopen(url)
    data = f.read().decode('utf-8')

    urbanDictParser = UrbanDictParser()
    try:
        urbanDictParser.feed(data)
    except IndexError:
        # apparently, nothing was returned
        pass

    if urbanDictParser.translations:
        html_text = ""
        the_definition = urbanDictParser.translations[0]
        html_text += '<b>"' + the_definition["word"] + '"</b>\n\n'
        if "def" in the_definition:
            html_text += _("<b>definition:</b> ")
            html_text += the_definition["def"].strip()
            html_text += '\n\n'
        if "example" in the_definition:
            html_text += _("<b>example:</b> ")
            html_text += the_definition["example"].strip()

        return html_text
    else:
        if term:
            return _('<i>no urban dictionary definition for "{}"</i>').format(
                term)
        return _('<i>no term from urban dictionary</i>')


def _initialise():
    plugins.register_user_command(["urbandict"])
