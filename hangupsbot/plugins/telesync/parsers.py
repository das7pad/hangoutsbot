"""parser to process telegram messages"""

from hangups.message_parser import Tokens

from sync.parser import MessageSegment, MessageParser

class TelegramMessageParser(MessageParser):
    """message parser to parse only line breaks and complete urls"""
    def __init__(self):
        super().__init__(Tokens.basic)

class TelegramMessageSegment(MessageSegment):
    """messae segment for text with no formatting"""
    _parser = TelegramMessageParser()
