#!/usr/bin/env python

import threading
import os
import socket
import datetime
import json

import gi
gi.require_version('Notify', '0.7')
from gi.repository import Notify
Notify.init('Timetracker')


from notifier import Notifier
from focustracker import FocusTracker
from pomodoro import PomodoroTimer


class WorkingHourManager(Notifier):
    def __init__(self, working_list, report_each_hour):
        self.focus_tracker = FocusTracker(working_list=working_list)
        self.pomodoro_timer = PomodoroTimer()
        self.working_list = working_list
        self.report_each_hour = report_each_hour
        self.timer_running = False


    def _handle_command(self, args, targets):
        want = "all" if len(args) < 1 else args[0]
        if want not in targets:
            return
        for target in targets[want]:
            threading.Thread(target=target).start()


    def _arm_report_timer(self):
        now = datetime.datetime.now()
        sleep = 3600 - now.timestamp() % 3600
        print("sleeping {}".format(sleep))
        if not self.timer_running:
            self.report_timer = threading.Timer(sleep, self._report_timer_callback)
            self.report_timer.start()
            self.timer_running = True


    def _report_timer_callback(self):
        self.report([])
        self._arm_report_timer()


    def run(self, args):
        targets = {
            "all": [self.focus_tracker.run, self.pomodoro_timer.run],
            "focus": [self.focus_tracker.run],
            "pomo": [self.pomodoro_timer.run]
        }
        self._handle_command(args, targets)

        if self.report_each_hour:
            self._arm_report_timer()


    def stop(self, args):
        targets = {
            "all": [self.focus_tracker.stop, self.pomodoro_timer.stop],
            "focus": [self.focus_tracker.stop],
            "pomo": [self.pomodoro_timer.stop]
        }
        self._handle_command(args, targets)

        if self.timer_running and self.report_timer:
            self.report_timer.cancel()
            self.report_timer = None
            self.timer_running = False


    def _time_format(self, seconds: int):
        if seconds is not None:
            seconds = int(seconds)
            d = seconds // (3600 * 24)
            h = seconds // 3600 % 24
            m = seconds % 3600 // 60
            s = seconds % 3600 % 60
            if d > 0:
                return '{:02d}D {:02d}H {:02d}m {:02d}s'.format(d, h, m, s)
            elif h > 0:
                return '{:02d}H {:02d}m {:02d}s'.format(h, m, s)
            elif m > 0:
                return '{:02d}m {:02d}s'.format(m, s)
            elif s > 0:
                return '{:02d}s'.format(s)
            return '-'


    def _report_focus(self, focus):
        fmt = "%m/%d %H:%M:%S"
        msg = "" if 'start_raw' not in focus else "Starting     :  {}".format(focus['start_raw'].strftime(fmt))

        def append(msg, fmt, field, newline=True):
            if newline and not msg.endswith('\n'):
                msg = msg + '\n'
            if field not in focus:
                return msg
            msg = msg + fmt.format(self._time_format(focus[field]))
            return msg

        msg = append(msg, "Total   time :  {}\n", 'total')
        msg = append(msg, "Working time :  {}", 'working')
        msg = append(msg, " ({})", 'working after last report', newline=False)
        msg = append(msg, "Playing time :  {}", 'playing')
        msg = append(msg, " ({})", 'playing after last report', newline=False)

        self.notify("Working hour report", msg)
        default = lambda o: f"<<non-serializable: {type(o).__qualname__}>>"
        print(json.dumps(focus, indent=4, sort_keys=True, default=default))
        pass


    def _report_pomodoro(self, pomo):
        print(json.dumps(pomo, indent=4, sort_keys=True))


    def report(self, args):
        typ = "all" if len(args) < 1 else args[0]
        if typ not in ["all", "working", "playing", "summary"]:
            print("wrong argument {}".format(typ))
            return

        focus = self.focus_tracker.report(typ)
        self._report_focus(focus)

        pomo = self.pomodoro_timer.report()
        self._report_pomodoro(pomo)


    def reset(self, args):
        self.focus_tracker.reset()
        self.pomodoro_timer.reset()


def run_server():
    server_address = '/tmp/timetracker.socket'
    try:
        os.unlink(server_address)
    except OSError:
        if os.path.exists(server_address):
            raise
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(server_address)
    return sock


def main():
    f = open('working.json')
    working_list = json.load(f)

    manager = WorkingHourManager(working_list=working_list, report_each_hour=True)
    cmds = {'run': manager.run, 'stop': manager.stop, 'report': manager.report, 'reset': manager.reset}
    sock = run_server()
    while True:
        raw, _ = sock.recvfrom(1024)
        data = raw.decode("utf-8").strip()
        toks = data.split()
        if len(toks) < 1:
            continue
        cmd, args = toks[0], toks[1:]
        print(cmd, args)
        if cmd == "quit" or cmd == "exit":
            sock.close()
            return
        if cmd in cmds:
            cmds[cmd](args)


if __name__ == '__main__':
    main()
