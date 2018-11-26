from hangupsbot.webbridge import (
    IncomingRequestHandler,
    WebFramework,
)


class BridgeInstance(WebFramework):
    """initialises the base framework
    to send messages to external chats, override
    WebFramework._send_to_external_chat()
    """


class IncomingMessages(IncomingRequestHandler):
    """request handler for incoming external chat events
    based on sinks.base_bot_request_handler
    override
        process_request()
        send_data()

    more info:
     https://github.com/hangoutsbot/hangoutsbot/wiki/Sinks-(2.4-and-above)
    """


def _initialise(bot):
    """config key "sample bridges must be defined for the bridge to initialise

    example format in config.json:
    "samplebridge": [
      {
        "certfile": "/root/selfsigned.pem",
        "name": "<SERVER NAME OR IP>",
        "port": <SERVER PORT>,
        "synced_conversations": ["<CONV ID 1>", "<CONV ID 2>"]
      }
    ],

    """
    BridgeInstance(bot, "samplebridge", IncomingMessages)
