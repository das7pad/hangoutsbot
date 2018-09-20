"""Hangupsbot plugin for user data storage by category with dynamic commands"""

from hangupsbot import plugins
from hangupsbot.commands import (
    Help,
    command,
)


_CATEGORY_HELP = {
    'set': _('Add or update your %(label)s.\n'
             'Usage: {bot_cmd} %(set_cmd)s %(upper_label)s'),
    'delete': _('Delete your %(label)s.\n'
                'Usage: {bot_cmd} %(delete_cmd)s'),
    'search': _('Search for %(label_plural)s by user or by %(label)s.\n'
                'Usage:\n'
                ' - {bot_cmd} %(search_cmd)s G+ ID\n'
                ' - {bot_cmd} %(search_cmd)s User Name\n'
                ' - {bot_cmd} %(search_cmd)s %(upper_label)s'),
}
_HELP = {
    'providedbyuser': _(
        'Manage the categories a user can add data into.\n'
        'Usage:\n'
        ' - {bot_cmd} providedbyuser add CATEGORY LABEL\n'
        '    Add a new category with the given label.\n'
        ' - {bot_cmd} providedbyuser delete CATEGORY\n'
        '    Delete the given category.\n'
        ' - {bot_cmd} providedbyuser list\n'
        '    Show all added categories.\n'
        ' - {bot_cmd} providedbyuser show CATEGORY\n'
        '    Show all user entries for the given label.'
    )
}


def _initialize(bot):
    """Check the storage and register the current categories

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
    """
    bot.config.set_defaults({'providedbyuser': {}})
    bot.memory.set_defaults({'providedbyuser': {}})

    for category in bot.config['providedbyuser']:
        register_category(bot, category)
    plugins.register_help(_HELP)
    plugins.register_admin_command(['providedbyuser'])


def register_category(bot, category):
    """check the storage and register the command and their help entries

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        category (str): the category name
    """
    path = ['providedbyuser', category]
    bot.memory.ensure_path(path)
    bot.config.ensure_path(path)

    meta = bot.config.get_by_path(path)
    label = meta.get('label', category)
    set_cmd = meta.get('set_cmd', 'set' + category)
    delete_cmd = meta.get('delete_cmd', 'delete' + category)
    search_cmd = meta.get('search_cmd', category)

    register_delete(category, label, delete_cmd)
    register_search(category, search_cmd)
    register_set(category, label, set_cmd)

    template_content = {
        'category': category,
        'label': label,
        'label_plural': meta.get('label_plural', label),
        'upper_label': label.upper(),
        'delete_cmd': delete_cmd,
        'search_cmd': search_cmd,
        'set_cmd': set_cmd,
    }
    category_help = {
        delete_cmd: _CATEGORY_HELP['delete'] % template_content,
        search_cmd: _CATEGORY_HELP['search'] % template_content,
        set_cmd: _CATEGORY_HELP['set'] % template_content,
    }
    plugins.register_help(category_help)


async def providedbyuser(bot, event, *args):
    """management command for categories

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.sync.event.SyncEvent): message data wrapper
        args (str): command arguments

    Returns:
        str: a command response

    Raises:
        Help: invalid query specified.
    """
    if not args or args[0] not in ('add', 'delete', 'list', 'show'):
        raise Help(_('Command is missing or is invalid!'))

    cmd = args[0]
    if cmd == 'add':
        if len(args) == 1:
            raise Help(_('Specify the category to be added!'))

        category = args[1]
        path = ['providedbyuser', category]
        if bot.config.exists(path):
            return _('The category %r already exists!') % category

        meta = {}
        if len(args) > 2:
            meta['label'] = ' '.join(args[2:])

        bot.config.set_by_path(path, meta)
        bot.config.save()

        await plugins.tracking.start({'module': 'providedbyuser',
                                      'module.path': __name__})

        register_category(bot, category=category)
        plugins.tracking.end()
        msg = _('Category %r added.')

    elif cmd == 'delete':
        if len(args) == 1:
            raise Help(_('Specify the category to be deleted!'))

        category = args[1]
        path = ['providedbyuser', category]
        try:
            bot.config.pop_by_path(path)
        except KeyError:
            msg = _('The category %r does not exist!') % category
        else:
            bot.config.save()
            try:
                bot.memory.pop_by_path(path)
            except KeyError:
                pass
            else:
                bot.memory.save()

            msg = _('Category %r deleted.') % category
            for cmd_name in ('set' + category, 'delete' + category, category):
                command.commands.pop(cmd_name)
                command.command_tagsets.pop(cmd_name)
                tracking = plugins.tracking.list[__name__]
                tracking['commands']['user'].remove(cmd_name)

    elif cmd == 'list':
        values = bot.memory['providedbyuser']
        lines = [_('There are no categories yet.')
                 if not values else
                 _('Registered categories:')]
        for category, entries in values.items():
            num = len(entries)
            if num == 1:
                template = _('- {category}: {num} entry')
            else:
                template = _('- {category}: {num} entries')
            lines.append(template.format(
                category=category, num=num))
        msg = '\n'.join(lines)

    else:
        if len(args) == 1:
            raise Help(_('Specify the category to show entries for!'))

        category = args[1]
        values = bot.memory.get_by_path(['providedbyuser', category])

        lines = [_('There are no entries yet.')
                 if not values else
                 _('User provided entries:')]
        for user_id, value in values.items():
            user = bot.sync.get_sync_user(user_id=user_id)
            lines.append(
                '- %s: %r' % (user.get_displayname(event.conv_id), value)
            )
        msg = '\n'.join(lines)

    return msg


def register_set(category, value_label, cmd_name):
    """factory for the setCATEGORY command

    Args:
        category (str): the category name
        value_label (str): a pretty name for the category
        cmd_name (str): a custom command name
    """
    @command.register(name=cmd_name, final=True)
    async def _cmd_set(bot, event, *args):
        """

        Args:
            bot (hangupsbot.core.HangupsBot): the running instance
            event (hangupsbot.sync.event.SyncEvent): message data wrapper
            args (str): command arguments

        Returns:
            str: a command response

        Raises:
            Help: the value is missing.
        """
        if not args:
            raise Help(_('%s not specified.') % value_label)

        path = ['providedbyuser', category, event.user_id.chat_id]
        try:
            last_value = bot.memory.pop_by_path(path)
        except KeyError:
            last_value = None

        value = ' '.join(args)
        bot.memory.set_by_path(path, value, create_path=False)
        bot.memory.save()
        if last_value is None:
            msg = _('{value!r} set as your {label}.').format(
                value=value, label=value_label)
        else:
            msg = _('Updated your {label} from {last!r} to {new!r}.').format(
                label=value_label, last=last_value, new=value)

        return msg

    plugins.register_user_command([cmd_name])


def register_delete(category, value_label, cmd_name):
    """factory for the deleteCATEGORY command

    Args:
        category (str): the category name
        value_label (str): a pretty name for the category
        cmd_name (str): a custom command name
    """
    @command.register(name=cmd_name, final=True)
    async def _cmd_delete(bot, event, *_dummy):
        """

        Args:
            bot (hangupsbot.core.HangupsBot): the running instance
            event (hangupsbot.sync.event.SyncEvent): message data wrapper
            _dummy (str): ignored command arguments

        Returns:
            str: a command response
        """
        path = ['providedbyuser', category, event.user_id.chat_id]
        try:
            last_value = bot.memory.pop_by_path(path)
        except KeyError:
            last_value = None
        else:
            bot.memory.save()

        if last_value is None:
            msg = _('There was no %s set.') % value_label
        else:
            msg = _('%s deleted.') % last_value
        return msg

    plugins.register_user_command([cmd_name])


def register_search(category, cmd_name):
    """factory for the CATEGORY search command

    Args:
        category (str): the category name
        cmd_name (str): a custom command name
    """
    @command.register(name=cmd_name, final=True)
    async def _cmd_search(bot, event, *args):
        """

        Args:
            bot (hangupsbot.core.HangupsBot): the running instance
            event (hangupsbot.sync.event.SyncEvent): message data wrapper
            args (str): command arguments

        Returns:
            str: a command response

        Raises:
            Help: invalid query specified.
        """
        if not args:
            raise Help(_('A search query is required!'))

        access_path = ['providedbyuser', category, 'access']
        try:
            conversation_or_alias = bot.config.get_by_path(access_path)
        except KeyError:
            pass
        else:
            conversation = bot.call_shared('alias2convid', conversation_or_alias)
            users = await bot.sync.get_users_in_conversation(
                conversation, profilesync_only=True)
            required_chat_id = event.user_id.chat_id
            for user in users:
                if user.id_.chat_id == required_chat_id:
                    break
            else:
                return _('Access denied!')

        query = ' '.join(args).lower()
        path = ['providedbyuser', category]
        values = bot.memory.get_by_path(path)
        matching = []
        for user_id, value in values.items():
            user = bot.sync.get_sync_user(user_id=user_id)
            if (user_id == query
                    or value.lower() == query
                    or query in user.full_name.lower()):
                matching.append((user, value))

        if not matching:
            return _('Your query matched zero entries.')

        lines = [_('Your query matched with %s entries:')
                 if len(matching) != 1 else
                 _('Your query matched with one entry:')]
        for user, value in matching:
            lines.append(
                '- %s: %r' % (user.get_displayname(event.conv_id), value)
            )
        return '\n'.join(lines)

    plugins.register_user_command([cmd_name])
