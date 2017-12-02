"""test `hangupsbot.config.Config`"""
__author__ = 'das7pad@outlook.com'

# TODO(das7pad): missing: io-operations
# TODO(das7pad): missing: `.validate`
# TODO(das7pad): missing: default coverage incl. `.set_default`

import pytest

import hangupsbot.config
from tests.constants import (
    CONFIG_PATH,
    CONV_ID_1,
    CONV_ID_2,
    CONFIG_DATA,
    CONFIG_DATA_DUMPED,
)

CONFIG_DEFAULT = object()
# pylint:disable=redefined-outer-name, protected-access

@pytest.fixture
def config():
    """get the loaded test-config instance

    for content see `CONFIG_DATA`

    Returns:
        hangupsbot.config.Config: loaded instance
    """
    cfg = hangupsbot.config.Config(path=CONFIG_PATH)
    cfg.default = CONFIG_DEFAULT
    cfg.config = CONFIG_DATA.copy()
    cfg._last_dump = CONFIG_DATA_DUMPED
    return cfg

def test_config_changed(config):
    assert not config._changed
    config['NEW'] = None
    assert config._changed
    del config['NEW']
    assert not config._changed

def test_config_get_option(config):
    assert config['one'] == {'two': {'three': None}}
    assert config['MISSING'] is CONFIG_DEFAULT

def test_config_get_by_path(config):
    assert config.get_by_path([]) == CONFIG_DATA

    existing_path = ['one', 'two', 'three']
    assert config.get_by_path(existing_path) is None

    non_existing_path = ['MISSING', 'two', 'three']
    with pytest.raises(KeyError):
        config.get_by_path(non_existing_path)

def test_config_exisits(config):
    existing_path = ['one', 'two', 'three']
    assert config.exists(existing_path)

    non_existing_path = ['MISSING', 'two', 'three']
    assert not config.exists(non_existing_path)

def test_config_ensure_path(config):
    existing_path = ['one', 'two', 'three']
    assert not config.ensure_path(existing_path)

    non_existing_path = ['MISSING', 'two', 'three']
    assert config.ensure_path(non_existing_path)
    assert config.exists(non_existing_path)

def test_config_set_by_path(config):
    path = ['one', 'two', 'three']
    value = object()
    config.set_by_path(path, value)

    assert config.get_by_path(path) is value

    non_existing_path = ['MISSING', 'two', 'three']
    with pytest.raises(KeyError):
        config.set_by_path(non_existing_path, value, create_path=False)

    config.set_by_path(non_existing_path, value, create_path=True)
    assert config.get_by_path(non_existing_path) is value

def test_config_pop_by_path(config):
    path = ['one', 'two', 'three']
    config.pop_by_path(path)
    assert not config.exists(path)

    non_existing_path = ['MISSING', 'two', 'three']
    with pytest.raises(KeyError):
        config.pop_by_path(non_existing_path)

def test_config_get_suboption(config):
    assert config.get_suboption('conversations', CONV_ID_1, 'PER_CONV')
    assert not config.get_suboption('conversations', CONV_ID_2, 'PER_CONV')

    assert config.get_suboption('conversations', CONV_ID_1, 'GLOBAL')

    val = config.get_suboption('conversations', CONV_ID_1, 'MISSING')
    assert val is CONFIG_DEFAULT
