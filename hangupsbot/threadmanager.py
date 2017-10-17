from threading import Thread

class ThreadManager(list):
    """storage for started threads"""
    tracking = None

    def set_tracking(self, tracking):
        """store the plugin tracking

        Args:
            thracking (plugins.Tracker): the current instance
        """
        self.tracking = tracking

    def register_thread(self, thread):
        """add a single Thread to the plugin tracking

        Args:
            thread (threading.Thread): a new thread
        """
        self.append(thread)
        self.tracking.register_thread(thread)

thread_manager = ThreadManager()                   # pylint:disable=invalid-name

def start_thread(target, args):
    thread = Thread(target=target, args=args)

    thread.daemon = True
    thread.start()
    thread_manager.register_thread(thread)
