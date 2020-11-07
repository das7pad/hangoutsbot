"""test the youtube integration"""

from hangupsbot.plugins.spotify.youtube import _get_title_from_html


def test_in_meta():
    blob = '''
        <meta name="title" content="Foo Bar">
    '''

    assert _get_title_from_html('', blob) == 'Foo Bar'


def test_in_title():
    blob = '''
        <title>Foo Bar - YouTube</title>
    '''

    assert _get_title_from_html('', blob) == 'Foo Bar'


def test_with_minus_in_title():
    blob = '''
        <title>Foo - Bar - YouTube</title>
    '''

    assert _get_title_from_html('', blob) == 'Foo - Bar'


def test_in_new_title():
    blob = '''
        <title>Foo Bar - YouTube New</title>
    '''

    assert _get_title_from_html('', blob) == 'Foo Bar'


def test_html_unescape():
    blob = '''
        <meta name="title" content="Foo &amp; Bar">
    '''

    assert _get_title_from_html('', blob) == 'Foo & Bar'
