"""hangups segment parser

more parsers and parser utility functions can be imported here
"""
#pylint: disable=unused-import
import hangups

from hangupsbot.parsers.kludgy_html_parser import segment_to_html

def simple_parse_to_segments(formatted_text):
    """parse text to hangups.ChatMessageSegements

    Args:
        formatted_text: string, html or markdown formatted text

    Returns:
        a list of hangups.ChatMessageSegment
    """
    return hangups.ChatMessageSegment.from_str(formatted_text)
