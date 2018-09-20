"""setup the test-env"""

from . import fixtures

# noinspection PyUnresolvedReferences
from .fixtures import (
    bot,
    event,
    module_wrapper,
)

__all__ = fixtures.__all__
