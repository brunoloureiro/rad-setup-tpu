import curses
import logging
import queue
import threading


class PrintManager(threading.Thread):
    # This is used to wait between the dequeue iterations
    __REFRESH_INTERVAL = 0.5

    def __init__(self, daemon: bool, *args, **kwargs):
        self._print_queue = queue.Queue()
        self._stop_event = threading.Event()
        super(PrintManager, self).__init__(daemon=daemon, *args, **kwargs)
        self.__current_print_dict = dict()
        self._std_scr = curses.initscr()


    def run(self):
        curses.cbreak()
        curses.noecho()

        try:
            # y, x = self._stdscr.getmaxyx()  # Get terminal dimensions
            # ... Display initialization, header, content formatting ...
            while self._stop_event.is_set() is False:
                while not self._print_queue.empty():
                    record: logging.LogRecord = self._print_queue.get()
                    self.__current_print_dict[f'{record.threadName}-{record.module}'] = record.msg
                self._std_scr.clear()
                # ... Clear lines, move cursor, print formatted content ...
                available_messages = "\n".join(self.__current_print_dict.values())
                self._std_scr.addstr(available_messages)

                self._std_scr.refresh()
                self._stop_event.wait(timeout=self.__REFRESH_INTERVAL)

        finally:
            curses.endwin()  # Clean up

    @property
    def print_queue(self) -> queue.Queue:
        return self._print_queue

    def stop(self) -> None:
        """ Stop the main function before join the thread """
        self._stop_event.set()
