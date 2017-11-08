"""constants for the slackrtm plugin"""

# Slack RTM event (sub-)types
CACHE_UPDATE_USERS = (
    'team_join',
    'user_change',
)
CACHE_UPDATE_GROUPS = (
    'group_join',
    'group_leave',
    'group_open',
    'group_close',
    'group_rename',
    'group_name',
    'group_archive',
    'group_unarchive',
)
CACHE_UPDATE_GROUPS_HIDDEN = (
    'group_open',
    'group_close',
    'group_rename',
    'group_name',
    'group_archive',
    'group_unarchive',
)
CACHE_UPDATE_CHANNELS = (
    'channel_join',
    'channel_leave',
    'channel_created',
    'channel_deleted',
    'channel_rename',
    'channel_archive',
    'channel_unarchive',
    'member_joined_channel',
)
CACHE_UPDATE_CHANNELS_HIDDEN = (
    'channel_created',
    'channel_deleted',
    'channel_rename',
    'channel_archive',
    'channel_unarchive',
    'member_joined_channel',
)
SYSTEM_MESSAGES = (
    'hello',
    'pong',
    'reconnect_url',
    'goodbye',
    'bot_added',
    'bot_changed',
    'dnd_updated_user',
    'emoji_changed',
    'desktop_notification',
    'presence_change',
    'user_typing',
)
CACHE_UPDATE_TEAM = (
    'team_rename',
    'team_domain_changed',
)
