"""hangups segment parser

more parsers and parser utility functions can be imported here
"""
#pylint: disable=unused-import
import hangups

from hangupsbot.sync.parser import get_formatted

def simple_parse_to_segments(formatted_text):
    """parse text to hangups.ChatMessageSegements

    Args:
        formatted_text: string, html or markdown formatted text

    Returns:
        a list of hangups.ChatMessageSegment
    """
    return hangups.ChatMessageSegment.from_str(formatted_text)

def segment_to_html(segment):
    """deprecated: parse the segment content to html

    Args:
        segment (hangups.ChatMessageSegment): message segment

    Returns:
        str: html formatted message segment
    """
    return get_formatted([segment,], 'html')
