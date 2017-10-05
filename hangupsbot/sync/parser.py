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

MARKDOWN_START_CHAR = r'*_~`=\\['
MARKDOWN_START_CHAR_POOL = re.compile(r'[%s]' % MARKDOWN_START_CHAR)
MARKDOWN_ESCAPE = re.compile(r'([%s])' % MARKDOWN_START_CHAR)
MARKDOWN_UNESCAPE = re.compile(r'\\([%s])' % MARKDOWN_START_CHAR)


class MessageParser(ChatMessageParser):
    """parser for markdown and html environments

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
    def replace_markdown(cls, text):
        """url-escape markdown formatting character

        Args:
            text (str): text with markdown formatting symbols

        Returns:
            str: escaped markdown text
        """
        def _single_replace(match):
            """url encode markdown char

            Args:
                match (_sre.SRE_Match): regex Match Object

            Returns:
                str: escaped text
            """
            char = match.group()
            return ('%5F' if char == '_' else
                    '%2A' if char == '*' else
                    '%7E' if char == '~' else
                    '%3D' if char == '=' else
                    '%5B' if char == '[' else
                    '%60' if char == '`' else
                    '%5C')

        return MARKDOWN_START_CHAR_POOL.sub(_single_replace, text)


class MessageSegmentHangups(hangups.ChatMessageSegment):
    """message segment that stores raw text and formatting

    parses html and markdown

    Args:
        see hangups.ChatMessageSegment
    """
    _parser = MessageParser()

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


class MessageSegmentInternal(MessageSegmentHangups):
    """message segment that stores text and formatting from internal formatting

    parses html only

    Args:
        text: string, message part without formatting
        kwargs: see MessageSegmentInternal
    """
    _parser = MessageParser(Tokens.basic + Tokens.html)


class MessageSegment(MessageSegmentHangups):
    """message segment that stores raw text and formatting

    parses html and markdown
    url-escapes markdown formatting found in the segment text

    Args:
        text: string, message part without formatting
        kwargs: see MessageSegmentInternal
    """
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
            if text == url or (url.startswith('http://') and text == url[7:]):
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
