"""parser to process telegram messages"""

from reparser import Segment
from hangups.message_parser import Tokens

from hangupsbot.sync.parser import MessageSegment, MessageParser

class TelegramMessageParser(MessageParser):
    """message parser to merge entities into text"""
    def __init__(self):
        super().__init__(Tokens.basic)

    def parse(self, text):
        """split entities

        Args:
            text (tuple): `(<str>, <list of dict>)`, message text and entities

        Returns:
            list[reparser.Segment]: parsed formatting segments
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

            last_pos = start_pos + entity['length']
            formatting = {'is_' + entity['type']: True}
            segments.append(Segment(text[start_pos:last_pos], **formatting))

        if last_pos < len(text):
            segments.extend(super().parse(text[last_pos:len(text)]))
        return segments

    def unescape_markdown(self, text):
        return text

class TelegramMessageSegment(MessageSegment):
    """message segment for telegram messages"""
    _parser = TelegramMessageParser()
