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
    get_formatted,
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
    """message segment for text with slack markdown formatting"""
    _parser = SlackMessageParser()

    @classmethod
    def from_str(cls, text):
        """parse a message to a sequence of MessageSegments

        Args:
            text (str): the text to parse

        Returns:
            list[SlackMessageSegment]: parsed formatting segments
        """
        segments = []
        split = text.split('\n')
        # formatting is only valid per line
        for line in split[:-1]:
            segments.extend(super().from_str(line))
            segments.append(SEGMENT_LINE_BREAK)
        segments.extend(super().from_str(split[-1]))
        return segments

def main():
    """check the parser"""
    print('***SLACK MARKDOWN TO HANGUPS')
    print('')

    text = ('Hello *bold* world!\n'
            'You can *try _this_ awesome* [link](www.eff.org).\n'
            '*title*\n'
            '*hello\n'
            '* world\n'
            '*\n'
            '_\n'
            '*\n'
            r'¯\_(ツ)_/¯'
            '\n<http://www.google.com.sg|Google Singapore> '
            '<http://www.google.com.my|Google Malaysia>\n'
            '<http://www.google.com|www.google.com>\n'
            'www.google.com\n'
            '**hello\n'
            '*** hi\n'
            '********\n'
            '_ xya kskdks')
    print(repr(text))
    print('')

    output = get_formatted(SlackMessageSegment.from_str(text), 'markdown')
    print('')

    print(repr(output))
    print('')

    print('***HANGUPS MARKDOWN TO SLACK PARSER')
    print('')

    segments = [
        MessageSegment(text='[bot] test markdown', is_bold=True),
        SEGMENT_LINE_BREAK,
        MessageSegment(
            text='ABCDEF ABCDEF',
            link_target='https://plus.google.com/u/0/1234567890/about'),
        SEGMENT_LINE_BREAK,
        MessageSegment(text='...('),
        MessageSegment(text='ABC@DEF.GHI', link_target='mailto:ABC@DEF.GHI'),
        MessageSegment(text=')'),
        SEGMENT_LINE_BREAK,
        MessageSegment(text='... 1234567890'),
        SEGMENT_LINE_BREAK,
        MessageSegment(
            text='XYZ XYZ',
            link_target='https://plus.google.com/u/0/1234567890/about',
            is_bold=True),
        SEGMENT_LINE_BREAK,
        MessageSegment(text='... 0123456789'),
        SEGMENT_LINE_BREAK,
        MessageSegment(text='`_Users: 2_`', is_bold=True),
        SEGMENT_LINE_BREAK,
        MessageSegment(text='`ABC (xyz)`', is_bold=True),
        MessageSegment(text=', chat_id = '),
        MessageSegment(text='1234567890', is_italic=True),
    ]
    print(repr(get_formatted(segments, 'markdown')))
    print('')

    output = get_formatted(segments, SLACK_STYLE)
    print('')

    print(repr(output))
    print('')

if __name__ == '__main__':
    main()
