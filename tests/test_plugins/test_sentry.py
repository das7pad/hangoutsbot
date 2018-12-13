"""test hangupsbot.plugins.sentry`"""
__author__ = 'Jakob Ackermann <das7pad@outlook.com>'

import logging

import pytest
import raven
import raven.handlers.logging

from hangupsbot import plugins

# run all tests in an event loop
pytestmark = pytest.mark.asyncio


logger = logging.getLogger(__name__)


def add_to_stack(client, **data):
    CAPTURE_STACK.append(data)
    client.logger.debug('send %r', data)


def get_from_stack():
    return CAPTURE_STACK.pop()


def check_message(
        exceptions: list,
        logger_name: str,
        message: str,
        template: str=None,
        template_params: tuple=None,
):
    assert CAPTURE_STACK, 'no message captured'
    data = get_from_stack()  # type: dict

    if 'exception' not in data:
        assert not exceptions, 'no exception captured'

    for actual_exception in data.get('exception', {}).get('values', []):
        expected_exception = exceptions.pop(0)
        assert actual_exception['type'] == expected_exception['type']
        assert actual_exception['value'] == expected_exception['value']

    assert not exceptions, '%r not captured' % exceptions

    assert data['logger'] == logger_name, 'logger name matches'
    assert data['message'] == message, 'message matches'
    if template:
        assert (data['sentry.interfaces.Message']['message']
                == template), 'template matches'
        assert (data['sentry.interfaces.Message']['params']
                == template_params), 'template parameter match'


CAPTURE_STACK = []
raven.Client.send = add_to_stack


async def test_load_plugin(bot):
    bot.config.set_by_path(['sentry', 'dsn'], 'https://secret@domain/project')
    bot.config.set_by_path(['sentry', 'options', 'raise_send_errors'], True)
    bot.config.set_by_path(['sentry', 'options', 'environment'], 'dev')
    await plugins.load(bot, 'plugins.sentry')
    check_loaded()


async def test_reload_plugin(bot):
    await plugins.reload_plugin(bot, 'plugins.sentry')
    check_loaded()


def check_loaded():
    if not raven.base.Raven:
        pytest.fail('Raven not configured', False)
        return

    if not raven.base.Raven.is_enabled():
        pytest.fail('Raven not active', False)
        return

    for handler in logging.getLogger().handlers:
        if isinstance(handler, raven.handlers.logging.SentryHandler):
            break
    else:
        pytest.fail('Sentry Logging Handler not deployed')


def raise_key_error(key):
    return {}[key]


def raise_key_error_from_key_error():
    try:
        return raise_key_error('INNER_KEY')
    except KeyError:
        return raise_key_error('OUTER_KEY')


async def test_exception_old_logger():
    try:
        raise_key_error('key of test_exception_old_logger')
    except KeyError:
        logger.exception('desc of test_exception_old_logger')

    check_message(
        exceptions=[
            {
                'type': 'KeyError',
                'value': "'key of test_exception_old_logger'",
            }
        ],
        logger_name=__name__,
        message='desc of test_exception_old_logger',
    )


async def test_exception_new_logger():
    new_logger = logging.getLogger(__name__ + '.new')
    try:
        raise_key_error('key of test_exception_new_logger')
    except KeyError:
        new_logger.exception('desc of test_exception_new_logger')

    check_message(
        exceptions=[
            {
                'type': 'KeyError',
                'value': "'key of test_exception_new_logger'",
            }
        ],
        logger_name=__name__ + '.new',
        message='desc of test_exception_new_logger',
    )


async def test_exception_in_exception():
    try:
        raise_key_error_from_key_error()
    except KeyError:
        logger.exception('desc of test_exception_in_exception')

    check_message(
        exceptions=[
            {
                'type': 'KeyError',
                'value': "'INNER_KEY'",
            },
            {
                'type': 'KeyError',
                'value': "'OUTER_KEY'",
            }
        ],
        logger_name=__name__,
        message='desc of test_exception_in_exception',
    )


async def test_error():
    logger.error('desc of test_error')

    check_message(
        exceptions=[],
        logger_name=__name__,
        message='desc of test_error'
    )


async def test_template():
    logger.error('desc of test_%s', 'template')

    check_message(
        exceptions=[],
        logger_name=__name__,
        message='desc of test_template',
        template='desc of test_%s',
        template_params=("'template'",)
    )


async def test_stack_from_error():
    try:
        raise_key_error('key of test_stack_from_error')
    except KeyError:
        logger.error('desc of test_stack_from_error')

    check_message(
        exceptions=[
            {
                'type': 'KeyError',
                'value': "'key of test_stack_from_error'",
            }
        ],
        logger_name=__name__,
        message='desc of test_stack_from_error',
    )


async def test_cleanup():
    """restore the logging.Logger methods"""
    assert CAPTURE_STACK == []

    for name, func in LOGGER_METHODS.items():
        setattr(logging.Logger, name, func)

# sentry will overwrite the Logging.Logger methods, save them beforehand
# noinspection PyDeprecation
LOGGER_METHODS = {
    'debug': logging.Logger.debug,
    'info': logging.Logger.info,
    'warning': logging.Logger.warning,
    'warn': logging.Logger.warn,
    'error': logging.Logger.error,
    'exception': logging.Logger.error,
    'critical': logging.Logger.critical,
    'fatal': logging.Logger.fatal,
    'log': logging.Logger.log,
}
