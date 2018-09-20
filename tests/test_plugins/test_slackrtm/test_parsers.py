"""test the parsers"""
__author__ = 'das7pad@outlook.com'

from hangupsbot.plugins.slackrtm import parsers
from hangupsbot.sync.parser import (
    MessageSegment,
    get_formatted,
)


SEGMENTS = [
    MessageSegment(text='test [slackmrkdwn]', is_bold=True),
    parsers.SEGMENT_LINE_BREAK,
    MessageSegment(text='0123*456*789', is_italic=True),
    parsers.SEGMENT_LINE_BREAK,
    MessageSegment(
        text='ABCDEF ABCDEF',
        link_target='https://plus.google.com/1234567890'),
    parsers.SEGMENT_LINE_BREAK,
    MessageSegment(text='*abc'),
    parsers.SEGMENT_LINE_BREAK,
    MessageSegment(
        text='XYZ XYZ',
        link_target='https://plus.google.com/u/0/1234567890/about',
        is_bold=True),
    parsers.SEGMENT_LINE_BREAK,
    MessageSegment(text='*Users: 2*', is_italic=True),
    parsers.SEGMENT_LINE_BREAK,
    MessageSegment(text='ABC (xyz)', is_bold=True),
    MessageSegment(text=', chat_id = '),
    MessageSegment(text='1234567890', is_italic=True),
    parsers.SEGMENT_LINE_BREAK,
    MessageSegment(text='ABCDEF', is_bold=True, is_italic=True),
    parsers.SEGMENT_LINE_BREAK,
]

# `code` parts should be skipped while parsing:
# SLACK_MRKDWN_OUT = SLACK_MRKDWN_IN.replace('`', '')
SLACK_MRKDWN_IN = (
    '*test [slackmrkdwn]*\n'
    '_0123*456*789_\n'
    '<https://plus.google.com/1234567890|ABCDEF ABCDEF>\n'
    '*abc\n'
    '*<https://plus.google.com/u/0/1234567890/about|XYZ XYZ>*\n'
    '_`*Users: 2*`_\n'
    '*`ABC (xyz)`*, chat_id = _1234567890_\n'
    '_*ABCDEF*_\n'
)
SLACK_MRKDWN_OUT = (
    '*test [slackmrkdwn]*\n'
    '_0123*456*789_\n'
    '<https://plus.google.com/1234567890|ABCDEF ABCDEF>\n'
    '*abc\n'
    '*<https://plus.google.com/u/0/1234567890/about|XYZ XYZ>*\n'
    '_*Users: 2*_\n'
    '*ABC (xyz)*, chat_id = _1234567890_\n'
    '_*ABCDEF*_\n'
)


def serialize(segments):
    """serialize parsed text segments

    Args:
        segments (list[MessageSegment]): message segments

    Returns:
        list[tuple[str, mixed]]: the serialized segments
    """
    return [sorted(seg.__dict__.items()) for seg in segments]


def test_segments_to_mrkdwn():
    assert get_formatted(SEGMENTS, parsers.SLACK_STYLE) == SLACK_MRKDWN_OUT


def test_mrkdwn_to_segments():
    parsed = parsers.SlackMessageSegment.from_str(SLACK_MRKDWN_IN)
    assert serialize(SEGMENTS) == serialize(parsed)


def test_multilevel_parsing():
    parsed = parsers.SlackMessageSegment.from_str(SLACK_MRKDWN_OUT)
    assert get_formatted(parsed, parsers.SLACK_STYLE) == SLACK_MRKDWN_OUT
