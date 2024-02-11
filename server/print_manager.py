import curses
import logging
import queue
import textwrap
import threading


class PrintManager(threading.Thread):
    # This is used to wait between the dequeue iterations
    __REFRESH_INTERVAL = 0.01

    def __init__(self, daemon: bool, *args, **kwargs):
        self.__print_queue = queue.Queue()
        self.__stop_event = threading.Event()
        super(PrintManager, self).__init__(daemon=daemon, *args, **kwargs)
        self.__current_print_dict = dict()
        self.__std_scr = curses.initscr()

    def run(self):
        curses.cbreak()
        curses.noecho()
        curses.start_color()  # Enable color support
        curses.use_default_colors()  # Use terminal's default color palette
        for i in range(0, curses.COLORS):
            curses.init_pair(i + 1, i, -1)  # Map color indices to different colors
        background_color = curses.COLOR_CYAN
        self.__std_scr.bkgd(background_color)

        while self.__stop_event.is_set() is False:
            while not self.__print_queue.empty():
                record: logging.LogRecord = self.__print_queue.get()
                key = f'{record.threadName}'
                message =(
                    f"{record.filename}:{record.lineno}--{record.funcName} "
                    f"[{record.levelname}] | {record.getMessage()}"
                )
                self.__current_print_dict[key] = message, record.asctime

            max_y, max_x = self.__std_scr.getmaxyx()

            # Display updates vertically, centered in available space
            y = 0
            for i, (module_name, message_data) in enumerate(self.__current_print_dict.items()):
                y += 1  # Move to next line for string
                string_to_print, asc_time = message_data

                # Display module name with appropriate color
                update_str = f" -- Last Updated:{asc_time}"
                self.__std_scr.addstr(y, 0, module_name, curses.color_pair(i % curses.COLORS + 1) | curses.A_BOLD)
                self.__std_scr.addstr(y, len(module_name), update_str, curses.COLOR_WHITE | curses.A_BOLD)

                y += 1
                wrapped_lines = textwrap.wrap(string_to_print, max_x - 2)  # Wrap within width
                for line in wrapped_lines:
                    self.__std_scr.addstr(y, 0, line.ljust(max_x - 2))
                    y += 1

                y += 1  # Add spacing between modules

            self.__std_scr.refresh()
            self.__stop_event.wait(timeout=self.__REFRESH_INTERVAL)

        curses.endwin()  # Clean up

    @property
    def print_queue(self) -> queue.Queue:
        return self.__print_queue

    def stop(self) -> None:
        """ Stop the main function before join the thread """
        self.__stop_event.set()
