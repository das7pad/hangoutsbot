"""pip setup for the hangupsbot"""

# TODO(das7pad): copy localisation

import glob
import os
import sys

from setuptools import setup

if sys.version_info < (3, 5, 0):
    # This is the minimum version to support async def
    raise RuntimeError("hangupsbot requires Python 3.5.0+")

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
            DEPENDENCY_LINKS.append(line)
        else:
            INSTALL_REQUIRES.append(line)

PACKAGES = [path[:-12].replace('/', '.')
            for path in glob.glob('hangupsbot/**/__init__.py', recursive=True)]

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
    package_data={
        'hangupsbot.plugins.image.image_linker_reddit': [
            'sauce.txt',
        ],
    },
)
