"""setup the test-env"""

import logging
import sys

LOGGING_FORMAT = (
    "%(relativeCreated)d "
    "%(levelname)s "
    "%(name)s[%(filename)s::%(funcName)s@L%(lineno)d]"
    ": %(message)s")

def pytest_report_header(config):
    verbose = config.getvalue('verbose')
    if verbose < 1:
        return 'Disabled logging'
    level = logging.DEBUG if verbose > 2 else logging.INFO
    logging.basicConfig(
        stream=sys.stdout,
        level=level,
        format=LOGGING_FORMAT,
    )
    out = 'Logging at level %s' % ('DEBUG' if verbose > 1 else 'INFO')
    return out
