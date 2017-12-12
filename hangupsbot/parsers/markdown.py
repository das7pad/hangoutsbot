"""deprecated html to markdown parser"""

__all__ = (
    'html_to_hangups_markdown',
)

from hangupsbot.sync.parser import get_formatted

def html_to_hangups_markdown(html):
    """deprecated: parse html to markdown

    Args:
        html (str): html formatted message

    Returns:
        str: markdown formatted message
    """
    return get_formatted(html, 'markdown')
