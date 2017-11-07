import os
import logging

import hangups

from hangupsbot import plugins


logger = logging.getLogger(__name__)


def _initialise(bot):
    file_writer = FileWriter(bot)

    if file_writer.initialised:
        plugins.register_handler(file_writer.on_membership_change, "membership")
        plugins.register_handler(file_writer.on_rename, "rename")
        plugins.register_handler(file_writer.on_chat_message, "allmessages")


class FileWriter(object):
    bot = None
    paths = []
    initialised = False

    def __init__(self, bot):
        self.bot = bot
        self.paths = []
        self.initialised = False

        chatlogger_path = bot.config.get_option('chatlogger.path')
        if chatlogger_path:
            self.paths.append(chatlogger_path)

        self.paths = list(set(self.paths))

        for path in self.paths:
            # create the directory if it does not exist
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                try:
                    os.makedirs(directory)
                except OSError:
                    logger.exception('cannot create path: %s', path)
                    continue

            logger.info("stored in: %s", path)

        if self.paths:
            self.initialised = True


    def _append_to_file(self, conversation_id, text):
        for path in self.paths:
            conversation_log = path + "/" + conversation_id + ".txt"
            with open(conversation_log, "a") as logfile:
                logfile.write(text)


    def on_chat_message(self, bot, event):
        event_timestamp = event.timestamp

        conversation_id = event.conv_id
        conversation_name = bot.conversations.get_name(event.conv)
        conversation_text = event.text

        user_full_name = event.user.full_name

        text = "--- {}\n{} :: {}\n{}\n".format(conversation_name, event_timestamp, user_full_name, conversation_text)

        self._append_to_file(conversation_id, text)


    def on_membership_change(self, bot, event):
        event_timestamp = event.timestamp

        conversation_id = event.conv_id
        conversation_name = bot.conversations.get_name(event.conv)

        user_full_name = event.user.full_name

        event_users = [event.conv.get_user(user_id) for user_id
                       in event.conv_event.participant_ids]
        names = ', '.join([user.full_name for user in event_users])

        if event.conv_event.type_ == hangups.MEMBERSHIP_CHANGE_TYPE_JOIN:
            text = "--- {}\n{} :: {}\nADDED: {}\n".format(conversation_name, event_timestamp, user_full_name, names)
        else:
            text = "--- {}\n{}\n{} left \n".format(conversation_name, event_timestamp, names)

        self._append_to_file(conversation_id, text)


    def on_rename(self, bot, event):
        event_timestamp = event.timestamp

        conversation_id = event.conv_id
        conversation_name = bot.conversations.get_name(event.conv)

        user_full_name = event.user.full_name

        text = "--- {}\n{} :: {}\nCONVERSATION RENAMED: {}\n".format(conversation_name, event_timestamp, user_full_name, conversation_name)

        self._append_to_file(conversation_id, text)
