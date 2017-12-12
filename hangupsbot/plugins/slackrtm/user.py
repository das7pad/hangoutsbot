"""Subclass of SyncUser for Slack users"""
__author__ = 'das7pad@outlook.com'

from hangupsbot.sync.user import SyncUser

class SlackUser(SyncUser):
    """get a sync user for a given user id from slack

    Args:
        slackrtm (core.SlackRTM): instance of the team, the user is attending
        channel (str): slack channel in which the user was found
        user_id (str): user id from slack or username, however only with the id
            a full user can be created
        name (str): users real name
        nickname (str): a parsed nickname
    """
    __slots__ = ('usr_id', 'username')

    def __init__(self, slackrtm, *, channel,
                 user_id=None, name=None, nickname=None):
        # slack specific username, may not be overwritten by `/bot setnickname`
        self.username = nickname or slackrtm.get_username(user_id, None)

        name = name or slackrtm.get_realname(user_id, self.username)
        if name == self.username:
            self.username = None
            if name is None:
                name = user_id

        photo = slackrtm.get_user_picture(user_id)

        url = 'https://{domain}.slack.com/team/{nick}'.format(
            domain=slackrtm.slack_domain,
            nick=self.username if self.username else name)

        self.usr_id = user_id
        identifier = slackrtm.identifier + ':%s' % channel
        super().__init__(identifier=identifier,
                         user_name=name, user_nick=self.username,
                         user_photo=photo, user_id=user_id, user_link=url,
                         user_is_self=(user_id == slackrtm.my_uid))
