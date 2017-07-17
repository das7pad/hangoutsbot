# Introduction

Hangupsbot is a chat bot designed for working with Google Hangouts.

Please see:
* [Instructions for installing](INSTALL.md)
* [Issue tracker](https://github.com/das7pad/hangoutsbot/issues) for bugs,
  issues and feature requests
* [Wiki](https://github.com/hangoutsbot/hangoutsbot/wiki) for everything else


## Repository Links
* [Translation Project](https://github.com/hangoutsbot/hangoutsbot-locales)
* [Reference Hangups Library](https://github.com/das7pad/hangups)


## Features
* **Mentions** :
  If somebody mentions you in a room, receive a private hangout from the bot
  with details on the mention, including context, room and person who mentioned
  you.
* **Syncouts** :
  A syncout is two Hangout group chats that have their messages forwarded to
  each other, allowing seamless interaction between the two rooms. Primarily
  used to beat the 150-member chat limit, but it can also be used for
  temporarily connecting teams together to interact.
* **Cross-chat Syncouts** :
  Half of your team is on Slack? No problem! You can connect them into the same
  room to communicate.
  Checkout telesync for using Telegram with the hangoutsbot.
* **[Hubot Integration](https://github.com/hangoutsbot/hangoutsbot/wiki/Hubot-Integration)**:
  Hangupsbot allows you to connect to [Hubot](https://hubot.github.com/), instantly providing you access
  to hundreds of developed chat tools and plugins.
* **Plugins and sinks** :
  The bot has [instructions for developing your own plugins and sinks](https://github.com/hangoutsbot/hangoutsbot/wiki/Authoring-Bot-Extensions),
  allowing the bot to interact with external services such as your company
  website, Google scripts and much more.
* **Plugin mania** :
  games, nickname support, subscribed keywords, customizable API -
  **[the list goes on](https://github.com/hangoutsbot/hangoutsbot/wiki/Plugin-List)**!

# Running The Bot

Note: **First run?** See the [installation instructions](INSTALL.md)

To execute: `/path/to/venv/bin/python3 hangupsbot.py`

```
usage: hangupsbot [-h] [-d] [--log LOG] [--cookies COOKIES] [--memory MEMORY] [--config CONFIG] [--version]

optional arguments:
-h, --help         show this help message and exit
-d, --debug        log detailed debugging messages (default: False)
--log LOG          log file path (default:
                   ~/.local/share/hangupsbot/hangupsbot.log)
--cookies COOKIES  cookie storage path (default:
                   ~/.local/share/hangupsbot/cookies.json)
--memory MEMORY    memory storage path (default:
                   ~/.local/share/hangupsbot/memory.json)
--config CONFIG    config storage path (default:
                   ~/.local/share/hangupsbot/config.json)
--version          show program's version number and exit
```

# Bot Configuration for Administrators

Configuration directives can be specified in `config.json`.

Please note that the `config.json` file supplied with the repository is not
  supposed to be edited/changed. It is the reference file used by the bot to
  create the actual configuration file located elsewhere in the system. To find
  out where the actual file is, please see the
  [**Additional Configuration** section](INSTALL.md#additional-configuration)
  in the [installation](INSTALL.md) instructions.

Most configuration directives are specified **globally**
* Global directives are always specified in the "root" of `config.json`.
* To specify a per-conversation directive, the same configuration option should
  be defined as `config.conversations[<conversation-id>].<configuration option>`.
* Per-conversation directives override global settings, if both are set.

## Plugins

The `plugins` key in `config.json` allows you to optionally specify a list of
  plugins that will be loaded by the bot on startup. If this option is left as
  `null`, then all available plugins will be loaded.

To specify the plugins to be loaded, first ensure that the correct `.py` files
  are inside your `hangupsbot/plugin/` directory, then modify the `plugins` key
  in `config.json` to reflect which plugins/files you want to load e.g.
    `plugins: ["mentions", "default", "chance", "syncrooms"]`

Some plugins may require extra configuration.
  `config.json` is the the configuration provider for the bot and its plugins.

Some interesting plugins:
* [mentions plugin](https://github.com/hangoutsbot/hangoutsbot/wiki/Mentions-Plugin)
  * alert users when their names are mentioned in a chat
* [subscribe plugin](https://github.com/hangoutsbot/hangoutsbot/wiki/Subscribe-Plugin)
  * alert users when keywords they are subscribed to are said in a chat
* [syncout / syncrooms plugins](https://github.com/hangoutsbot/hangoutsbot/wiki/Syncouts-Plugin)
  * relay chat messages between different hangout group conversations (syncrooms)
  * configure via bot commands (syncrooms_config)

The wiki has a more comprehensive
  **[list of plugins](https://github.com/hangoutsbot/hangoutsbot/wiki/Plugin-List)**

# Interacting with the Bot

There are two general types of interactions with the bot:
* **`/bot` commands** begin with `/bot` e.g. `/bot dosomething`
  * some bot commands are admin-only
* custom interactions (usage and accessibility varies by plugin)

The base bot supports some basic command even without any plugins loaded.
  Here is a partial list:

`/bot help`
* Bot lists all supported commands in a private message with the user

`/bot ping`
* Bot replies with a `pong`.

`/bot version`
* Bot replies with the version number of the framework

A full list of commands supported by the base framework is available at the
  [**Core Commands**](https://github.com/hangoutsbot/hangoutsbot/wiki/Core-Commands)
  wiki page.

# Updating

* Navigate to the repository directory (eg. `cd ~/hangupsbot`)
* Change to the latest stable branch using `git checkout master`
* `git pull` to pull the latest version of hangupsbot
* `./venv/bin/pip3 install -r requirements.txt --upgrade`
* Restart the bot

# Debugging

* Run the bot with the `-d` parameter e.g. `./venv/bin/python3 hangupsbot.py -d`
  - this lowers the log level to `DEBUG` for a more verbose and informative log
  file.
* `tail -F` the log file, which is probably located at
  `/<user>/.local/share/hangupsbot/hangupsbot.log` - the location varies by
  distro!
* A second log file `<name of the default logfile>_warnings.log` is created to
  catch log messages on level WARNING and above to find break points faster.
* Console output (STDOUT) is limited to level WARNING and above in normal mode,
  level DEBUG is applied in debug mode.

## Tips for troubleshooting
**Program isn't running:**
* [Update `hangupsbot` and its dependecies](#updating)
* Run `./venv/bin/hangups` to check if the original hangups library is working
  * If there are errors, delete the cookie at
    `~/.local/share/hangupsbot/cookies.json` and try again
  * Log into your Google Account from the server's address.

**Bot isn't responding to messages:**
* Check that the chats are not going into the 'Invites' section of Hangouts.

# Extending

Please see
  https://github.com/hangoutsbot/hangoutsbot/wiki/Authoring-Bot-Extensions

# Credits / History

Hangoutsbot is derived from
  [hangupsbot](https://github.com/hangoutsbot/hangoutsbot)

On 2017-07-17, this fork was made standalone
