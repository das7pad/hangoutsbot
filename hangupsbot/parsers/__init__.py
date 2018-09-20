"""hangups segment parser

more parsers and parser utility functions can be imported here
"""

__all__ = (
    'segment_to_html',
    'simple_parse_to_segments',
)

from hangupsbot.sync.parser import (
    MessageSegmentHangups,
    get_formatted,
)


def simple_parse_to_segments(formatted_text):
    """deprecated: parse text to hangups.ChatMessageSegments

    Args:
        formatted_text (str): html or markdown formatted text

    Returns:
        list[hangups.ChatMessageSegment]: parsed formatting segments
    """
    return MessageSegmentHangups.from_str(formatted_text)

def segment_to_html(segment):
    """deprecated: parse the segment content to html

    Args:
        segment (hangups.ChatMessageSegment): message segment

    Returns:
        str: html formatted message segment
    """
    return get_formatted([segment,], 'html')
