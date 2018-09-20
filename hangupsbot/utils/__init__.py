"""utils used by the HangupsBot core"""
# coding: utf-8
# pylint: disable=unused-import
import importlib
import logging
import os
import traceback
import unicodedata

# noinspection PyUnresolvedReferences
from hangupsbot.parsers import (
    segment_to_html,
    simple_parse_to_segments,
)


BASE_PATH = os.path.dirname(os.path.dirname(__file__)) + '/'

def print_to_logger(*args, **dummys):
    """redirect the input to a logger with the name of the last entry in stack

    Args:
        args (mixed): a tuple with entries of any type
        dummys (dict): capture kwargs that are not used
    """
    caller = traceback.extract_stack()[-2]
    module = caller.filename.replace(BASE_PATH, '').replace('/', '.').replace(
        '.__init__.py', '').replace('.py', '')
    logging.getLogger('%s.%s()' % (module, caller.name)).info(*args)

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
        module_name (str): module path relative to the main script
        class_name (str): class name in the module

    Returns:
        mixed: the requested class

    Raises:
        ImportError: module not found or error on loading
        AttributeError: module has no class named class_name
    """
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


class FormatBaseException(Exception):
    """A base Exception which uses %s formatting for the string representation

    requires a `._template` member to pass the provided arguments into it
    """
    _template = 'Template is missing'
    def __str__(self):
        base = '%s: %s' % (self.__class__.__name__, self._template)
        required_args = base.count('%s')
        args = self.args + ('<missing>',) * (required_args - len(self.args))
        return base % args[:required_args]

    def __repr__(self):
        return self.__str__()
