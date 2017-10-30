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

# allow packages to overwrite requirements:
# e.g. `pkg==0.1` from `requirements.txt` with own update `pkg==0.2.1`:
#      `git+https://github.com/username/reponame@identifier#egg=pkg==pkg-0.2.1`
DEPENDENCY_LINK_EGGS = []
for line in DEPENDENCY_LINKS:
    for item in line.split('#'):
        if item[:4] == 'egg=':
            # add `pkg==pkg-0.2.1`
            DEPENDENCY_LINK_EGGS.append(item[4:])
for dependency in INSTALL_REQUIRES.copy():
    # find package `pkg`
    package = dependency.split('==')[0]
    extra_dependency = None
    for extra_dependency in DEPENDENCY_LINK_EGGS:
        if extra_dependency.startswith(package):
            break
    else:
        continue
    INSTALL_REQUIRES.remove(dependency) # drop the old version tag

    # parse `pkg==pkg-0.2.1` to `pkg==0.2.1` and add it into the requirements
    raw_extra_dependency_version = extra_dependency.split('==', 1)[-1]
    INSTALL_REQUIRES.append(raw_extra_dependency_version.replace('-', '==', 1))


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
        'hangupsbot': [
            'config.json',
        ],
    },
)
