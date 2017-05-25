# coding: utf-8
# pylint: disable=unused-import
import importlib
import logging
import unicodedata

from parsers import simple_parse_to_segments, segment_to_html

from permamem import name_from_hangups_conversation


logger = logging.getLogger(__name__)

def remove_accents(text):
    """remove accents from unicode text, allows east asian languages through"""
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')


def unicode_to_ascii(text):
    """Transliterate unicode characters to ASCII"""
    return unicodedata.normalize('NFKD',
                                 text).encode('ascii', 'ignore').decode()


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
