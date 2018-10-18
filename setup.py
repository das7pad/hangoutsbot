"""pip setup for the hangupsbot"""

import glob
import json
import os
import re
import sys

from setuptools import setup

if sys.version_info < (3, 5, 3):
    # This is the minimum version to support async-def and aiohttp>=3
    raise RuntimeError("hangupsbot requires Python 3.5.3+")

VERSION_PATH = os.path.join(os.path.dirname(__file__), 'hangupsbot/version.py')
with open(VERSION_PATH, 'r') as file:
    VERSION = file.read().strip().split(' ')[-1].strip('"')

INSTALL_REQUIRES = []
DEPENDENCY_LINKS = []
with open('requirements.txt', 'r') as file:
    for line in file:
        line = line.strip()
        if not line or line[0] == '#':
            continue
        if '//' in line:
            if line.startswith('-e '):
                line = line[3:]
            DEPENDENCY_LINKS.append(line)
        else:
            INSTALL_REQUIRES.append(line)

# parse packages and their version from urls:
# e.g. `pkg==0.2.1` from
#      `git+https://github.com/username/reponame@v0.2.1#egg=pkg`
REGEX_TAG_NAME = re.compile(r'.*@v(?P<version>.+)#egg=(?P<name>.+)')
for line in DEPENDENCY_LINKS:
    match = REGEX_TAG_NAME.match(line)
    if not match:
        continue

    dependency_locked = match.group('name') + '==' + match.group('version')
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
