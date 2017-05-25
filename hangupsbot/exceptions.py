class SuppressHandler(Exception):
    pass

class SuppressAllHandlers(Exception):
    pass

class SuppressEventHandling(Exception):
    pass

class HangupsBotExceptions:
    SuppressHandler = SuppressHandler
    SuppressAllHandlers = SuppressAllHandlers
    SuppressEventHandling = SuppressEventHandling
