# coding: utf-8
import importlib, logging, unicodedata

import hangups_shim as hangups

from parsers import simple_parse_to_segments, segment_to_html

from permamem import name_from_hangups_conversation


logger = logging.getLogger(__name__)


def text_to_segments(text):
    """Create list of message segments from text"""
    # Replace two consecutive spaces with space and non-breakable space,
    # then split text to lines
    lines = text.replace('  ', ' \xa0').splitlines()
    if not lines:
        return []

    # Generate line segments
    segments = []
    for line in lines[:-1]:
        if line:
            segments.append(hangups.ChatMessageSegment(line))
        segments.append(hangups.ChatMessageSegment('\n', hangups.SegmentType.LINE_BREAK))
    if lines[-1]:
        segments.append(hangups.ChatMessageSegment(lines[-1]))

    return segments


def remove_accents(text):
    """remove accents from unicode text, allows east asian languages through"""
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def unicode_to_ascii(text):
    """Transliterate unicode characters to ASCII"""
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()


def class_from_name(module_name, class_name):
    """adapted from http://stackoverflow.com/a/13808375

    Args:
        module_name: string, modulepath relative to the main script
        class_name: string, class name in the module

    Returns:
        Class, requested item

    Raises:
        ImportError: module not found or error on loading
        AttributeError: module has no class named class_name
    """
    module = importlib.import_module(module_name)
    return getattr(module, class_name)
