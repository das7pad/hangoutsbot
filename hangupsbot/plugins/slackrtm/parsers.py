"""parser to process slack markdown"""
# -*- coding: utf-8 -*-

from reparser import (
    Token,
    MatchGroup,
)

from hangups.message_parser import markdown, Tokens, url_complete
from hangups.hangouts_pb2 import SEGMENT_TYPE_LINE_BREAK

from hangupsbot.sync.parser import (
    MessageSegment,
    MessageParser,
)


SLACK_STYLE = {
    (0, 0, 0): '{text}',
    (1, 0, 0): '*{text}*',
    (0, 1, 0): '_{text}_',
    (1, 1, 0): '_*{text}*_',
    (0, 0, 1): '<{url}|{text}>',
    (1, 0, 1): '*<{url}|{text}>*',
    (0, 1, 1): '_<{url}|{text}>_',
    (1, 1, 1): '_*<{url}|{text}>*_',
    'line_break': '\n',
    'ignore_links_matching_text': True,
    'allow_hidden_url': True,
    'escape_html': False,
    'escape_markdown': False,
}

SEGMENT_LINE_BREAK = MessageSegment(text='\n',
                                    segment_type=SEGMENT_TYPE_LINE_BREAK)


MRKDWN_LINK = r'<(?P<url>.*?)\|(?P<text>.*?)>'

TOKENS_SLACK = [
    Token('slack_b', *markdown(r'\*'), is_bold=True),
    Token('slack_i', *markdown(r'_'), is_italic=True),
    Token('slack_pre1', *markdown(r'`'), skip=True),
    Token('slack_pre2', *markdown(r'```'), skip=True),
    Token('slack_strike', *markdown(r'~'), is_strikethrough=True),
    Token('slack_link', MRKDWN_LINK, text=MatchGroup('text'),
          link_target=MatchGroup('url', func=url_complete)),
]


class SlackMessageParser(MessageParser):
    """message parser for slack markdown"""
    def __init__(self):
        super().__init__(TOKENS_SLACK + Tokens.basic)

    def unescape_markdown(self, text):
        return text


class SlackMessageSegment(MessageSegment):
    """messae segment for text with slack markdown formatting"""
    _parser = SlackMessageParser()

    @classmethod
    def from_str(cls, text):
        """parse a message to a sequence of MessageSegments

        Args:
            text (str): the text to parse

        Returns:
            list: a list of `SlackMessageSegment` instances
        """
        segments = []
        split = text.split('\n')
        # formatting is only valid per line
        for line in split[:-1]:
            segments.extend(super().from_str(line))
            segments.append(SEGMENT_LINE_BREAK)
        segments.extend(super().from_str(split[-1]))
        return segments
