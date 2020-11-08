"""pip setup for the hangupsbot"""

import glob
import json
import pathlib
import re
import sys

from setuptools import setup


if sys.version_info < (3, 6):
    raise RuntimeError("hangupsbot requires Python 3.6")

REPO = pathlib.Path(__file__).parent  # type: pathlib.Path

VERSION_PATH = REPO / 'hangupsbot' / 'version.py'
VERSION = VERSION_PATH.read_text().strip().split(' ')[-1].strip('"')

INSTALL_REQUIRES = []
EDITABLE_LINKS = []
REQUIREMENTS_PATH = REPO / 'requirements' / 'requirements.txt'
for line in REQUIREMENTS_PATH.read_text().split('\n'):
    line = line.strip()
    if not line or line[0] == '#':
        continue
    if line.startswith('-e '):
        EDITABLE_LINKS.append(line)
    else:
        INSTALL_REQUIRES.append(line)

# pip requirements vs setuptools is a mess with editable url-dependencies:
#  - pip requirement editable   : `-e URL@TAG#egg=pkg`
#    NOTE: the TAG must to be v prefixed
#  - setuptools install_requires: `pkg @ URL`
#
# The requirements.txt file stores the pip compatible scheme.
# Parse the lines for the setuptools here:
REGEX_REQUIREMENT = re.compile(r'-e (?P<url>\S+)#egg=(?P<name>.+)')
for line in EDITABLE_LINKS:
    match = REGEX_REQUIREMENT.match(line)
    if not match:
        raise RuntimeError(
            'Requirement %r has an incompatible scheme, required: %r'
            % (
                line,
                REGEX_REQUIREMENT.pattern,
            )
        )

    compat_line = '{name} @ {url}'.format(
        **match.groupdict()
    )
    INSTALL_REQUIRES.append(compat_line)

PACKAGES = [path[:-12].replace('/', '.')
            for path in glob.glob('hangupsbot/**/__init__.py', recursive=True)]

PACKAGE_DATA = {}
for path in glob.glob('hangupsbot/**/package_data.json', recursive=True):
    with open(path, 'r') as file:
        PACKAGE_DATA.update(json.load(file))

setup(
    name='hangupsbot',
    version=VERSION,
    install_requires=INSTALL_REQUIRES,
    packages=PACKAGES,
    entry_points={
        'console_scripts': [
            'hangupsbot=hangupsbot.__main__:main',
        ],
    },
    package_data=PACKAGE_DATA,
)
