"""sync parser"""
__author__ = 'das7pad@outlook.com'

import html as html_module
import logging
import urllib.parse
import re

import hangups
import hangups.hangouts_pb2
from hangups.message_parser import ChatMessageParser, Tokens

logger = logging.getLogger(__name__)

# dict keys: (bold, italic, is_link)
STYLE_MAPPING = {
    "text": {
        (0, 0, 0): '{text}',
        (1, 0, 0): '{text}',
        (0, 1, 0): '{text}',
        (1, 1, 0): '{text}',
        (0, 0, 1): '{url}({text})',
        (1, 0, 1): '{url}({text})',
        (0, 1, 1): '{url}({text})',
        (1, 1, 1): '{url}({text})',
        'line_break': '\n',
        'ignore_links_matching_text': True,
        'allow_hidden_url': False,
        'escape_html': False,
        'escape_markdown': False,
    },
    "html_flat": {
        (0, 0, 0): '{text}',
        (1, 0, 0): '<b>{text}</b>',
        (0, 1, 0): '<i>{text}</i>',
        (1, 1, 0): '<b>{text}</b>',
        (0, 0, 1): '<a href="{url}">{text}</a>',
        (1, 0, 1): '<a href="{url}">{text}</a>',
        (0, 1, 1): '<a href="{url}">{text}</a>',
        (1, 1, 1): '<a href="{url}">{text}</a>',
        'line_break': '\n',
        'ignore_links_matching_text': True,
        'allow_hidden_url': True,
        'escape_html': True,
        'escape_markdown': False,
    },
    "html": {
        (0, 0, 0): '{text}',
        (1, 0, 0): '<b>{text}</b>',
        (0, 1, 0): '<i>{text}</i>',
        (1, 1, 0): '<b><i>{text}</i></b>',
        (0, 0, 1): '<a href="{url}">{text}</a>',
        (1, 0, 1): '<b><a href="{url}">{text}</a></b>',
        (0, 1, 1): '<i><a href="{url}">{text}</a></i>',
        (1, 1, 1): '<b><i><a href="{url}">{text}</a></i></b>',
        'line_break': '\n',
        'ignore_links_matching_text': True,
        'allow_hidden_url': True,
        'escape_html': True,
        'escape_markdown': False,
    },
    "internal": {
        (0, 0, 0): '{text}',
        (1, 0, 0): '<b>{text}</b>',
        (0, 1, 0): '<i>{text}</i>',
        (1, 1, 0): '<b><i>{text}</i></b>',
        (0, 0, 1): '<a href="{url}">{text}</a>',
        (1, 0, 1): '<b><a href="{url}">{text}</a></b>',
        (0, 1, 1): '<i><a href="{url}">{text}</a></i>',
        (1, 1, 1): '<b><i><a href="{url}">{text}</a></i></b>',
        'line_break': '\n',
        'ignore_links_matching_text': True,
        'allow_hidden_url': True,
        'escape_html': True,
        'escape_markdown': True,
    },
    "hangouts": {
        # almost full html, links should have text and target matching
        # messages are parsed twice to support sending as string,
        #  non formatting markdown must to be escaped
        (0, 0, 0): '{text}',
        (1, 0, 0): '<b>{text}</b>',
        (0, 1, 0): '<i>{text}</i>',
        (1, 1, 0): '<b><i>{text}</i></b>',
        (0, 0, 1): '<a href="{url}">{text}</a>',
        (1, 0, 1): '<b><a href="{url}">{text}</a></b>',
        (0, 1, 1): '<i><a href="{url}">{text}</a></i>',
        (1, 1, 1): '<b><i><a href="{url}">{text}</a></i></b>',
        'line_break': '\n',
        'ignore_links_matching_text': True,
        'allow_hidden_url': False,
        'escape_html': False,
        'escape_markdown': True,
    },
    "markdown_flat": {
        (0, 0, 0): '{text}',
        (1, 0, 0): '**{text}**',
        (0, 1, 0): '*{text}*',
        (1, 1, 0): '**{text}**',
        (0, 0, 1): '[{text}]({url})',
        (1, 0, 1): '[{text}]({url})',
        (0, 1, 1): '[{text}]({url})',
        (1, 1, 1): '[{text}]({url})',
        'line_break': '\n',
        'ignore_links_matching_text': True,
        'allow_hidden_url': True,
        'escape_html': False,
        'escape_markdown': True,
    },
    "markdown": {
        (0, 0, 0): '{text}',
        (1, 0, 0): '**{text}**',
        (0, 1, 0): '*{text}*',
        (1, 1, 0): '***{text}***',
        (0, 0, 1): '[{text}]({url})',
        (1, 0, 1): '[**{text}**]({url})',
        (0, 1, 1): '[*{text}*]({url})',
        (1, 1, 1): '[***{text}***]({url})',
        'line_break': '\n',
        'ignore_links_matching_text': True,
        'allow_hidden_url': True,
        'escape_html': False,
        'escape_markdown': True,
    }
}

MARKDOWN_START_CHAR = '*_~`='
MARKDOWN_CHAR = MARKDOWN_START_CHAR + '\\'
MARKDOWN_ESCAPE = re.compile(r'([%s])' % MARKDOWN_START_CHAR)
MARKDOWN_UNESCAPE = re.compile(r'\\([%s])' % MARKDOWN_START_CHAR)


class MessageParserInternal(ChatMessageParser):
    """message parser for internal messages

    does not escape or replace markdown
    unescapes markdown in parsed segments with .unescape_markdown

    Args:
        tokens: list of reparser.Token instances
    """
    @staticmethod
    def postprocess(text):
        # single tokens such as links are not covered by this method,
        # unescape in .parse all segments instead
        return text

    def parse(self, text):
        def _unescape_segment(segment):
            """unescape markdown in the parsed segment

            Args:
                segment: reparser.Segment instance

            Returns:
                the segment instance having text and link target unescaped
            """
            segment.text = self.unescape_markdown(segment.text)
            link_target = (self.unescape_markdown(segment.params['link_target'])
                           if 'link_target' in segment.params else None)
            segment.params['link_target'] = link_target
            return segment

        logger.debug('%s.parse: %s', self.__class__.__name__, repr(text))

        return (_unescape_segment(segment) for segment in super().parse(text))

    @staticmethod
    def unescape_markdown(text):
        """unescape escaped markdown

        Args:
            text: string, backslash escaped markdown

        Returns:
            string, unescaped markdown
        """
        return MARKDOWN_UNESCAPE.sub(r'\1', text)


class MessageParser(MessageParserInternal):
    """parser for markdown and html environments

    url-escapes invalid markdown formatting with .replace_bad_markdown

    Args:
        tokens: list of reparser.Token instances
    """
    def preprocess(self, text):
        return super().preprocess(self.replace_bad_markdown(text))

    @classmethod
    def replace_bad_markdown(cls, text):
        """escape bad markdown formatting

        saves urls with markdown chars

        Args:
            text: string, text with mixed formatting

        Returns:
            string, text with valid markdown per line
        """
        lines = (cls.replace_markdown(line,
                                      char=[char for char in MARKDOWN_START_CHAR
                                            if line.count(char) % 2])
                 for line in text.split('\n'))
        return '\n'.join(lines)

    @staticmethod
    def escape_markdown(text):
        """escape markdown formatting

        Args:
            text: string, markdown formatted text

        Returns:
            string, backslash escaped markdown
        """
        return MARKDOWN_ESCAPE.sub(r'\\\1', text)

    @classmethod
    def replace_markdown(cls, text, char=MARKDOWN_CHAR):
        """escape markdown formatting character

        saves urls with markdown chars

        Args:
            text: string, text with markdown formatting symbols
            char: string, character to escape

        Returns:
            string, escaped markdown text
        """
        def _single_replace(part, replace_char):
            """url encode markdown char

            Args:
                part: string, text part to escape
                replace_char: char to replace in part

            Returns:
                string, escaped text
            """
            if not replace_char:
                # performace
                return part
            if '_' in replace_char:
                part = part.replace('_', '%5F').replace('\\_', '%5F')
            if '*' in replace_char:
                part = part.replace('*', '%2A').replace('\\*', '%2A')
            if '~' in replace_char:
                part = part.replace('~', '%7E').replace('\\~', '%7E')
            if '=' in replace_char:
                part = part.replace('=', '%3D').replace('\\=', '%3D')
            if '[' in replace_char:
                part = part.replace('[', '%5B').replace('\\[', '%5B')
            if '`' in replace_char:
                part = part.replace('`', '%60').replace('\\`', '%60')
            if '\\' in replace_char:
                part = part.replace('\\', '%5C')
            return part

        if 'http' not in text:
            # performace
            return _single_replace(text, char)

        # replace all markdown char in a url
        return ' '.join(_single_replace(word, MARKDOWN_CHAR)
                        if 'http' in word else _single_replace(word, char)
                        for word in text.split(' '))


class MessageSegmentInternal(hangups.ChatMessageSegment):
    """message segment that stores text and formatting from internal formatting

    parses html only

    Args:
        see hangups.ChatMessageSegment
    """
    _parser = MessageParserInternal(Tokens.basic + Tokens.html)

    @classmethod
    def from_str(cls, text):
        """parse a message to a sequence of MessageSegments

        Args:
            text: str, text to parse

        Returns:
            a list of ChatMessageSegment instances
        """
        return [cls(segment.text, **segment.params)
                for segment in cls._parser.parse(text)]


class MessageSegmentHangups(MessageSegmentInternal):
    """message segment that stores raw text and formatting

    parses html and markdown

    Args:
        text: string, message part without formatting
        kwargs: see MessageSegmentInternal
    """
    _parser = MessageParserInternal()


class MessageSegment(MessageSegmentInternal):
    """message segment that stores raw text and formatting

    parses html and markdown
    url-escapes markdown formatting found in the segment text

    Args:
        text: string, message part without formatting
        kwargs: see MessageSegmentInternal
    """
    _parser = MessageParser()

    def __init__(self, text, **kwargs):
        super().__init__(self._parser.replace_markdown(text),
                         **kwargs)

    @classmethod
    def replace_markdown(cls, segments):
        """escape markdown as formatting is already part of the segments

        called on a subclass of MessageSegment, the subclasses message parser
         and subclass will be used to escape markdown and create new instances

        Args:
            segments: list of MessageSegment instances

        Returns:
            new list of MessageSegments with escaped markdown
        """
        # do not alter the original segments
        return [cls(seg.text,
                    segment_type=seg.type_,
                    is_bold=seg.is_bold,
                    is_italic=seg.is_italic,
                    is_strikethrough=seg.is_strikethrough,
                    is_underline=seg.is_underline,
                    link_target=seg.link_target)
                for seg in segments]


def get_formatted(segments, raw_style, *, internal_source=False):
    """parse a text input and format the segments with a given style

    Args:
        segments: list of ChatMessageSegments or a string
        raw_style: string, target style key in .STYLE_MAPPING
            or dict, a custom style covering all formatting cases
        internal_source: boolean, set to True to disable markdown escape

    Returns:
        string, formated segment text

    Raises:
        ValueError: invalid style provided
    """
    def _get_style():
        """verify the provided style

        Returns:
            dict, a valid formatting style

        Raises:
            ValueError: invalid style provided
        """
        if isinstance(raw_style, dict):
            if any(key not in raw_style for key in STYLE_MAPPING['text']):
                missing = (set(STYLE_MAPPING['text'].keys())
                           - set(raw_style.keys()))
                raise ValueError('missing keys in style: %s' % repr(missing))
            style = raw_style

        elif isinstance(raw_style, str) and raw_style in STYLE_MAPPING:
            style = STYLE_MAPPING[raw_style]

        else:
            raise ValueError('not allowed style: %s' % raw_style)
        return style

    style = _get_style()
    if not isinstance(segments, list):
        segments = (MessageSegmentInternal.from_str(segments)
                    if internal_source else
                    MessageSegment.from_str(segments))

    lines = ['']
    for segment in segments:
        url = segment.link_target
        text = segment.text
        if segment.type_ == hangups.hangouts_pb2.SEGMENT_TYPE_LINK:
            if url.startswith(('https://www.google.com/url?q=',
                               'http://www.google.com/url?q=')):
                # Note: Google adds tracking to urls sent via Hangouts, but
                #  the url text still contains the original url
                url = text
            if text in url:
                if style['ignore_links_matching_text']:
                    url = None
            elif not style['allow_hidden_url']:
                text = '{} [{}]'.format(url, text)
                url = None
        elif segment.type_ != hangups.hangouts_pb2.SEGMENT_TYPE_TEXT:
            lines.append('')
            continue

        if raw_style != 'internal':
            # unescape the quoted special charater and escape as needed
            text = urllib.parse.unquote(text)
            text = (html_module.escape(text, quote=False)
                    if style['escape_html'] else text)
            text = (MessageParser.escape_markdown(text)
                    if style['escape_markdown'] else text)

        template = style[segment.is_bold, segment.is_italic, int(bool(url))]

        lines[-1] += template.format(text=text, url=url)

    return style['line_break'].join(lines)
