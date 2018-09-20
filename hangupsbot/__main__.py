"""entrypoint to start the bot"""

import argparse
import logging
import logging.config
import os
import shutil
import sys

import appdirs

from hangupsbot import (
    config,
    version,
)


def configure_logging(args):
    """Configure Logging

    If the user specified a logging config file, open it, and
    fail if unable to open. If not, attempt to open the default
    logging config file. If that fails, move on to basic
    log configuration.
    """

    log_level = "DEBUG" if args.debug else "INFO"

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "service": {
                "format": "%(levelname)s %(name)s: %(message)s",
            },
            "default": {
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "level": "DEBUG" if args.debug else "WARNING",
                "formatter": "service" if args.service else "default",
            },
            "file": {
                "class": "logging.FileHandler",
                "filename": args.log,
                "level": "DEBUG",
                "formatter": "default",
            },
            "file_warnings": {
                "class": "logging.FileHandler",
                "filename": args.log.rsplit(".", 1)[0] + "_warnings.log",
                "level": "WARNING",
                "formatter": "default",
            }
        },
        "loggers": {
            # base config, applies to all logger
            "": {
                "handlers": ["file", "console", "file_warnings"],
                "level": log_level
            },
            # adjust the log-level for modules explicit:

            ## security: do not expose tokens to the log file
            "urllib3.connectionpool": {"level": "INFO"},
            "requests": {"level": "INFO"},

            ## adjust noisy module logger
            "asyncio": {"level": "WARNING"},
            "hangups": {"level": "WARNING"},

            ## ignore the addition of fallback users
            "hangups.user": {"level": "ERROR"},

            ## do not log disconnects twice, we already attach a logger to
            ## our `hangups.Client.on_disconnect` event
            "hangups.channel": {"level": "ERROR"},
        }
    }

    # Temporarily bring in the configuration file, just so we can configure
    # logging before bringing anything else up. There is no race internally,
    # if logging() is called before configured, it outputs to stderr, and
    # we will configure it soon enough
    boot_config = config.Config(args.config)
    try:
        boot_config.load()
    except (OSError, IOError, ValueError):
        pass
    else:
        if boot_config.exists(["logging.system"]):
            logging_config = boot_config["logging.system"]

    logging.config.dictConfig(logging_config)

def main():
    """Main entry point"""
    # Build default paths for files.
    user_dirs = appdirs.AppDirs("hangupsbot")
    default_base_dir = user_dirs.user_data_dir
    files = {
        'log': 'hangupsbot.log',
        'cookies': 'cookies.json',
        'config': 'config.json',
        'memory': 'memory.json',
    }

    def get_path(file, base=default_base_dir):
        """Create the full path for a given file

        Args:
            file (str): one of `log`, `cookies`, `config`, `memory`
            base (str): a custom base dir

        Returns:
            str: the full path
        """
        return os.path.join(base, files[file])

    # Configure argument parser
    parser = argparse.ArgumentParser(
        prog="hangupsbot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-d", "--debug", action="store_true",
                        help=_("log detailed debugging messages"))
    parser.add_argument("-s", "--service", action="store_true",
                        help=_("strip the timestamp from the stdout-log"))
    parser.add_argument("--base_dir", default=default_base_dir,
                        help=_("base dir for the log-, cookies-, config- "
                               "and memory-path"))
    parser.add_argument("--log", default=get_path('log'),
                        help=_("log file path"))
    parser.add_argument("--cookies", default=get_path('cookies'),
                        help=_("cookie storage path"))
    parser.add_argument("--memory", default=get_path('memory'),
                        help=_("memory storage path"))
    parser.add_argument("--config", default=get_path('config'),
                        help=_("config storage path"))
    parser.add_argument("--retries", default=5, type=int,
                        help=_("Maximum disconnect / reconnect retries before "
                               "quitting"))
    parser.add_argument("--version", action="version",
                        version="%(prog)s {}".format(version.__version__),
                        help=_("show program's version number and exit"))
    args = parser.parse_args()

    # Update the paths for all files in case they are not specified explicit
    if args.base_dir != default_base_dir:
        # custom base dir set
        for item in ('log', 'cookies', 'config', 'memory'):
            user_path = getattr(args, item)
            if user_path == get_path(item):
                # no custom path set, update it with the new base dir
                setattr(args, item, get_path(item, args.base_dir))

    # Create all necessary directories.
    for path in (args.log, args.cookies, args.config, args.memory):
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            try:
                os.makedirs(directory)
            except OSError as err:
                sys.exit(_("Failed to create directory: %s") % err)

    # If there is no config file in user data directory, copy default one there
    if not os.path.isfile(args.config):
        try:
            shutil.copy(
                os.path.abspath(os.path.join(os.path.dirname(__file__),
                                             "config.json")),
                args.config)
        except (OSError, IOError) as err:
            sys.exit(_("Failed to copy default config file: %s") % err)

    configure_logging(args)

    from hangupsbot.core import HangupsBot

    # initialise the bot
    bot = HangupsBot(args.cookies, args.config, args.memory, args.retries)

    # start the bot
    bot.run()


if __name__ == '__main__':
    main()
