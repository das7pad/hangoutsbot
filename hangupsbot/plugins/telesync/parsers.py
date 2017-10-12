"""parser to process telegram messages"""

from reparser import Segment
from hangups.message_parser import Tokens

from hangupsbot.sync.parser import MessageSegment, MessageParser

class TelegramMessageParser(MessageParser):
    """message parser to merge entities into text"""
    def __init__(self):
        super().__init__(Tokens.basic)

    def parse(self, text):
        """unbreak entities

        Args:
            text: tuple of string and list of dicts, message text and entities

        Returns:
            list, a list of reparser.Segment instances
        """
        text, entities = text
        segments = []
        last_pos = 0
        for entity in entities:
            if entity['type'] not in ('bold', 'italic'):
                continue
            start_pos = entity['offset']
            if start_pos > last_pos:
                segments.extend(super().parse(text[last_pos:start_pos]))

            last_pos += entity['length']
            formatting = {'is_' + entity['type']: True}
            segments.append(Segment(text[start_pos:last_pos], **formatting))

        if last_pos < len(text):
            segments.extend(super().parse(text[last_pos:len(text)]))
        return segments

class TelegramMessageSegment(MessageSegment):
    """messae segment for telegram messages"""
    _parser = TelegramMessageParser()
