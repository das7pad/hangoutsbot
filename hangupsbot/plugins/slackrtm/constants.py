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
    'member_left_channel',
)
CACHE_UPDATE_CHANNELS_HIDDEN = (
    'channel_created',
    'channel_deleted',
    'channel_rename',
    'channel_archive',
    'channel_unarchive',
    'member_joined_channel',
    'member_left_channel',
)
SYSTEM_MESSAGES = (
    'hello',
    'pong',
    'reconnect_url',
    'goodbye',
    'desktop_notification',
    'pref_change',
    'bot_added',
    'bot_changed',
    'emoji_changed',
    'dnd_updated',
    'dnd_updated_user',
    'user_typing',
    'im_marked',
    'group_marked',
    'channel_marked',
    'presence_change',
    'manual_presence_change',
    'im_history_changed',
    'channel_history_changed',
    'group_history_changed',
    'subteam_created',
    'subteam_members_changed',
    'subteam_self_added',
    'subteam_self_removed',
    'subteam_updated',
    'team_migration_started',
    'team_plan_change',
    'team_pref_change',
    'team_profile_change',
    'team_profile_delete',
    'team_profile_reorder',
)
CACHE_UPDATE_TEAM = (
    'team_rename',
    'team_domain_changed',
)

# message type / subtype
MESSAGE_TYPES_TO_SKIP = (
    'file_created', 'file_public', 'file_change',
    'file_shared', 'file_unshared',
    'file_comment_added', 'file_comment_deleted', 'file_comment_edited',
    'message_deleted',
)
MESSAGE_SUBTYPES_MEMBERSHIP_JOIN = ('channel_join', 'group_join')
MESSAGE_SUBTYPES_MEMBERSHIP_LEAVE = ('channel_leave', 'group_leave')
