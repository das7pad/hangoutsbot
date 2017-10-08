
import io
import logging
import os
import re
import urllib.error
import urllib.request

import json
import datetime

import aiohttp
import hangups
from TwitterAPI import TwitterAPI, TwitterConnectionError
from bs4 import BeautifulSoup

import plugins
from commands import Help

logger = logging.getLogger(__name__)

def prettydate(diff):
    s = diff.seconds
    if diff.days > 7 or diff.days < 0:
        return diff.strftime('%d %b %y')
    elif diff.days == 1:
        return '1 day ago'
    elif diff.days > 1:
        return '{} days ago'.format(diff.days)
    elif s <= 1:
        return 'just now'
    elif s < 60:
        return '{} seconds ago'.format(s)
    elif s < 120:
        return '1 minute ago'
    elif s < 3600:
        return '{} minutes ago'.format(round(s/60))
    elif s < 7200:
        return '1 hour ago'
    return '{} hours ago'.format(round(s/3600))

def _initialise():
    plugins.register_admin_command(["twitterkey", "twittersecret", 'twitterconfig'])
    plugins.register_sync_handler(_watch_twitter_link, "message_once")

def twittersecret(bot, dummy, *args):
    '''Set your Twitter API Secret. Get one from https://apps.twitter.com/app'''
    if not args:
        raise Help()
    secret = args[0]
    if not bot.memory.get_by_path(['twitter']):
        bot.memory.set_by_path(['twitter'], {})

    bot.memory.set_by_path(['twitter', 'secret'], secret)
    return "Twitter API secret set to <b>{}</b>.".format(secret)

def twitterkey(bot, dummy, *args):
    '''Set your Twitter API Key. Get one from https://apps.twitter.com/'''
    if not args:
        raise Help()
    key = args[0]
    if not bot.memory.get_by_path(['twitter']):
        bot.memory.set_by_path(['twitter'], {})

    bot.memory.set_by_path(['twitter', 'key'], key)
    return "Twitter API key set to <b>{}</b>.".format(key)

def twitterconfig(bot, *dummys):
    '''Get your Twitter credentials. Remember that these are meant to be kept secret!'''

    if not bot.memory.exists(['twitter']):
        bot.memory.set_by_path(['twitter'], {})
    if not bot.memory.exists(['twitter', 'key']):
        bot.memory.set_by_path(['twitter', 'key'], "")
    if not bot.memory.exists(['twitter', 'secret']):
        bot.memory.set_by_path(['twitter', 'secret'], "")

    return ("<b>API key:</b> {}<br><b>API secret:</b> {}".format(
        bot.memory.get_by_path(['twitter', 'key']),
        bot.memory.get_by_path(['twitter', 'secret'])))

async def _watch_twitter_link(bot, event):
    if event.user.is_self:
        return

    if " " in event.text:
        return

    if not re.match(r"^https?://(www\.)?twitter.com/[a-zA-Z0-9_]{1,15}/status/[0-9]+$", event.text, re.IGNORECASE):
        return

    try:
        key = bot.memory.get_by_path(['twitter', 'key'])
        secret = bot.memory.get_by_path(['twitter', 'secret'])
        tweet_id = re.match(r".+/(\d+)", event.text).group(1)
        api = TwitterAPI(key, secret, auth_type="oAuth2")
        tweet = json.loads(api.request('statuses/show/:{}'.format(tweet_id)).text)
        text = re.sub(r'(\W)@(\w{1,15})(\W)', r'\1<a href="https://twitter.com/\2">@\2</a>\3', tweet['text'])
        text = re.sub(r'(\W)#(\w{1,15})(\W)', r'\1<a href="https://twitter.com/hashtag/\2">#\2</a>\3', text)
        time = tweet['created_at']
        timeago = prettydate(datetime.datetime.now(tz=datetime.timezone.utc) - datetime.datetime.strptime(time, '%a %b %d %H:%M:%S %z %Y'))
        username = tweet['user']['name']
        twhandle = tweet['user']['screen_name']
        userurl = "https://twitter.com/intent/user?user_id={}".format(tweet['user']['id'])
        message = "<b><u><a href='{}'>@{}</a> ({})</u></b>: {} <i>{}</i>".format(userurl, twhandle, username, text, timeago)
        try:
            images = tweet['extended_entities']['media']
            for image in images:
                if image['type'] == 'photo':
                    imagelink = image['media_url']
                    filename = os.path.basename(imagelink)
                    async with aiohttp.ClientSession() as session:
                        async with session.request('get', imagelink) as res:
                            raw = await res.read()
                    image_data = io.BytesIO(raw)
                    image_id = await bot.upload_image(image_data,
                                                      filename=filename)
                    await bot.coro_send_message(event.conv.id_, None,
                                                image_id=image_id)

        except KeyError:
            pass

        await bot.coro_send_message(event.conv, message)
    except (TwitterConnectionError, aiohttp.ClientError, hangups.NetworkError):
        url = event.text.lower()
        try:
            response = urllib.request.urlopen(url)
        except urllib.error.URLError as e:
            logger.info("Tried and failed to get the twitter status text:(")
            logger.info(e.reason)
            return

        username = re.match(r".+twitter\.com/([a-zA-Z0-9_]+)/", url).group(1)
        body = response.read()
        soup = BeautifulSoup(body.decode("utf-8"), "lxml")
        twhandle = soup.title.text.split(" on Twitter: ")[0].strip()
        tweet = re.sub(r"#([a-zA-Z0-9]*)", r"<a href='https://twitter.com/hashtag/\1'>#\1</a>", soup.title.text.split(" on Twitter: ")[1].strip())
        message = "<b><a href='{}'>@{}</a> [{}]</b>: {}".format("https://twitter.com/{}".format(username), username, twhandle, tweet)
        await bot.coro_send_message(event.conv, message)
