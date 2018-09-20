import asyncio
import logging
import logging.handlers
import sys

from hangupsbot import plugins
from hangupsbot.base_models import BotMixin


logger = logging.getLogger(__name__)


def _initialise():
    plugins.register_admin_command([
        "lograise",
        "logconfig",
    ])

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if handler.__class__.__name__ == "ChatMessageLogger":
            logger.info("ChatMessageLogger already attached")
            return

    chat_handler = ChatMessageLogger()

    chat_handler.setFormatter(
        logging.Formatter("<b>%(levelname)s %(name)s </b>: %(message)s"))
    chat_handler.setLevel(logging.WARNING)
    chat_handler.addFilter(PluginFilter())

    root_logger.addHandler(chat_handler)


def logconfig(bot, dummy, logger_name, level):
    if logger_name in sys.modules:
        config_logging = bot.get_config_option("logging") or {}

        mapping = {
            "critical": 50,
            "error": 40,
            "warning": 30,
            "info": 20,
            "debug": 10,
        }

        effective_level = 0
        if level.isdigit():
            effective_level = int(level)
            if effective_level < 0:
                effective_level = 0
        elif level.lower() in mapping:
            effective_level = mapping[level]

        if effective_level == 0:
            if logger_name in config_logging:
                del config_logging[logger_name]
            message = "logging: {} disabled".format(effective_level)

        else:
            if logger_name in config_logging:
                current = config_logging[logger_name]
            else:
                current = {"level": 0}

            current["level"] = effective_level

            config_logging[logger_name] = current
            message = "logging: {} set to {} / {}".format(logger_name,
                                                          effective_level, level)

        bot.config.set_by_path(["logging"], config_logging)
        bot.config.save()

    else:
        message = "logging: {} not found".format(logger_name)

    return message


def lograise(dummy0, dummy1, *args):
    level = (''.join(args) or "DEBUG").upper()

    if level == "CRITICAL":
        logger.critical("This is a CRITICAL log message")
    elif level == "ERROR":
        logger.error("This is an ERROR log message")
    elif level == "WARNING":
        logger.warning("This is a WARNING log message")
    elif level == "INFO":
        logger.info("This is an INFO log message")
    elif level == "DEBUG":
        logger.debug("This is a DEBUG log message")


class PluginFilter(logging.Filter, BotMixin):

    def filter(self, record):
        logging_cfg = self.bot.get_config_option("logging") or {}
        if not logging_cfg:
            return False

        if record.name not in logging_cfg:
            return False

        if record.levelno < logging_cfg[record.name]["level"]:
            return False

        return True


class ChatMessageLogger(logging.Handler, BotMixin):

    def emit(self, record):
        message = self.format(record)
        convs = self.bot.conversations.get("tag:receive-logs")
        for conv_id in convs.keys():
            asyncio.ensure_future(self.bot.coro_send_message(conv_id, message))
