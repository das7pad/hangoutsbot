"""pip setup for the hangupsbot"""

import glob
import json
import pathlib
import re
import sys

from setuptools import setup


if sys.version_info < (3, 5, 3):
    # This is the minimum version to support async-def and aiohttp>=3
    raise RuntimeError("hangupsbot requires Python 3.5.3+")

REPO = pathlib.Path(__file__).parent  # type: pathlib.Path

VERSION_PATH = REPO / 'hangupsbot' / 'version.py'
VERSION = VERSION_PATH.read_text().strip().split(' ')[-1].strip('"')

INSTALL_REQUIRES = []
DEPENDENCY_LINKS = []
REQUIREMENTS_PATH = REPO / 'requirements.txt'
for line in REQUIREMENTS_PATH.read_text().split('\n'):
    line = line.strip()
    if not line or line[0] == '#':
        continue
    if '//' in line:
        if line.startswith('-e '):
            line = line[3:]
        DEPENDENCY_LINKS.append(line)
    else:
        INSTALL_REQUIRES.append(line)

# pip and setuptools are not compatible here, their url schemes:
#  - pip       : `...#egg=pkg`
#  - setuptools: `...#egg=pkg-version`
# The requirements.txt file stores the pip compatible ones.
# Parse the urls for the setuptools here:
# Support urls like this one, which includes the version as a tag/branch:
#  `git+https://github.com/user/repo@v0.2.1#egg=pkg`
REGEX_TAG_NAME = re.compile(r'.*@v(?P<version>.+)#egg=(?P<name>.+)')
for line in DEPENDENCY_LINKS.copy():
    match = REGEX_TAG_NAME.match(line)
    if not match:
        raise RuntimeError(
            '%r has an incompatible scheme, use a "v" prefixed tag or branch'
            % line
        )

    dependency_locked = match.group('name') + '==' + match.group('version')

    DEPENDENCY_LINKS.remove(line)
    DEPENDENCY_LINKS.append(line + '-' + match.group('version'))
    INSTALL_REQUIRES.append(dependency_locked)

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
    dependency_links=DEPENDENCY_LINKS,
    packages=PACKAGES,
    entry_points={
        'console_scripts': [
            'hangupsbot=hangupsbot.__main__:main',
        ],
    },
    package_data=PACKAGE_DATA,
)
