"""parser to process telegram messages"""

from reparser import Segment
from hangups.message_parser import Tokens

from hangupsbot.sync.parser import MessageSegment, MessageParser

class TelegramMessageParser(MessageParser):
    """message parser to merge entities into text"""
    def __init__(self):
        super().__init__(Tokens.basic)

    def parse_entities(self, text, entities):
        """split entities

        Args:
            text (str): text without formatting
            entities (list[dict]): formatting entities

        Returns:
            list[reparser.Segment]: parsed formatting segments
        """
        segments = []
        last_pos = 0
        for entity in entities:
            if entity['type'] not in ('bold', 'italic'):
                continue
            start_pos = entity['offset']
            if start_pos > last_pos:
                segments.extend(self.parse(text[last_pos:start_pos]))

            last_pos = start_pos + entity['length']
            formatting = {'is_' + entity['type']: True}
            segments.append(Segment(text[start_pos:last_pos], **formatting))

        if last_pos < len(text):
            segments.extend(self.parse(text[last_pos:len(text)]))
        return segments

    def unescape_markdown(self, text):
        return text

class TelegramMessageSegment(MessageSegment):
    """message segment for telegram messages"""
    _parser = TelegramMessageParser()

    @classmethod
    def from_text_and_entities(cls, text, entities):
        """parse a formatted message to a sequence of TelegramMessageSegments

        Args:
            text (str): text to parse
            entities (list[dict]): formatting entities

        Returns:
            list[TelegramMessageSegment]: parsed formatting segments
        """
        return [cls(segment.text, **segment.params)
                for segment in cls._parser.parse_entities(text, entities)]
