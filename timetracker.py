#!/usr/bin/env python

import threading
import os
import socket
import subprocess
import re
import datetime
import time
import ctypes
import ctypes.util
import json

import gi
gi.require_version('Notify', '0.7')
from gi.repository import Notify
Notify.init('Timetracker')


class Notifier(object):
    def notify(self, title, msg):
        notify = Notify.Notification.new(title, msg)
        notify.show()


class IdleTracker(object):
    def __init__(self):

        class XScreenSaverInfo(ctypes.Structure):
            _fields_ = [
                ("window", ctypes.c_ulong),  # screen saver window
                ("state", ctypes.c_int),  # off, on, disabled
                ("kind", ctypes.c_int),  # blanked, internal, external
                ("since", ctypes.c_ulong),  # milliseconds
                ("idle", ctypes.c_ulong),  # milliseconds
                ("event_mask", ctypes.c_ulong),
            ]  # events

        lib_x11 = self._load_lib("X11")
        # specify required types
        lib_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib_x11.XOpenDisplay.restype = ctypes.c_void_p
        lib_x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib_x11.XDefaultRootWindow.restype = ctypes.c_uint32
        # fetch current settings
        self.display = lib_x11.XOpenDisplay(None)
        self.root_window = lib_x11.XDefaultRootWindow(self.display)

        self.lib_xss = self._load_lib("Xss")
        # specify required types
        self.lib_xss.XScreenSaverQueryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(XScreenSaverInfo),
        ]
        self.lib_xss.XScreenSaverQueryInfo.restype = ctypes.c_int
        self.lib_xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
        # allocate memory for idle information
        self.xss_info = self.lib_xss.XScreenSaverAllocInfo()


    def get_idle_time(self):
        self.lib_xss.XScreenSaverQueryInfo(self.display, self.root_window, self.xss_info)
        return self.xss_info.contents.idle / 1000


    def _load_lib(self, name: str):
        path = ctypes.util.find_library(name)
        if path is None:
            raise OSError("Could not find library `{name}`")
        return ctypes.cdll.LoadLibrary(path)


class FocusTracker(Notifier):
    IdleForeground = "Unknown"

    idle = 0
    tracking = 1

    class App(object):
        def __init__(self, name):
            self.name = name
            self.total = 0
            self.details = {}
            self.working = 0
            self.working_details = {}
            self.playing = 0
            self.playing_details = {}


        def track(self, misc, secs, working):
            self.total += secs
            self.details[misc] = self.details[misc] + secs if misc in self.details else secs
            if working:
                self.working += secs
                self.working_details[misc] = self.working_details[misc] + secs if misc in self.working_details else secs
            else:
                self.playing += secs
                self.playing_details[misc] = self.playing_details[misc] + secs if misc in self.playing_details else secs


        def report(self, typ="all"):
            preset = {"all": (self.total, self.details),
                      "working": (self.working, self.working_details),
                      "playing": (self.playing, self.playing_details)}
            if typ not in preset:
                return {}
            else:
                rep = preset[typ]
                return {"total": rep[0], "details": rep[1]}


    def __init__(self, working_list):
        self.duration = 5
        self.stopping = True
        self.idle_tracker = IdleTracker()
        self.idle_threshold = 180
        self.working_list = working_list
        self._reset()


    def _reset(self):
        self.apps = {}
        self.working_hour = 0
        self.playing_hour = 0
        self.working_after_last_report = 0
        self.playing_after_last_report = 0
        self.last_track = datetime.datetime.now()
        self.state = FocusTracker.idle
        self.start = None


    def report(self, typ):
        res = {'start': self.start.__str__()}
        res = {'start_raw': self.start}
        app_details = typ != "summary"
        typ = typ if typ != "summary" else "all"

        if typ == "all":
            res["total"] = self.working_hour + self.playing_hour
            res["working after last report"] = self.working_after_last_report
            res["playing after last report"] = self.playing_after_last_report
            self.working_after_last_report = 0
            self.playing_after_last_report = 0
        if typ == "all" or typ == "working":
            res["working"] = self.working_hour
        if typ == "all" or typ == "playing":
            res["playing"] = self.playing_hour

        if app_details:
            for name, app in self.apps.items():
                rep = app.report(typ)
                if "total" not in rep or rep["total"] == 0:
                    continue
                res[name] = rep
        return res


    def get_wm_name(xprop_id, default):
        for line in xprop_id:
            match = re.match("WM_NAME\((?P<type>.+)\) = (?P<name>.+)", line)
            if match != None:
                type = match.group("type")
                if type == "STRING" or type == "COMPOUND_TEXT" or type == "UTF8_STRING":
                    wm_name = match.group("name")
                    return wm_name
        return default


    def get_wm_class(xprop_id, default):
        for line in xprop_id:
            match = re.match("WM_CLASS\(.*\) = (?P<inst>.+), (?P<class>.+)", line)
            if match != None:
                return match.group("class")
        return default


    def get_active_window_title(self):
        wm_name = FocusTracker.IdleForeground
        wm_class = FocusTracker.IdleForeground

        idle_time = self.idle_tracker.get_idle_time()
        if idle_time > self.idle_threshold:
            return wm_class, wm_name

        root = subprocess.run(['xprop', '-root'],  stdout=subprocess.PIPE)
        if root.stdout == "":
            return wm_class, wm_name

        root_stdout = root.stdout.decode('utf-8').split('\n')
        found = False
        for i in root_stdout:
            if '_NET_ACTIVE_WINDOW(WINDOW):' in i:
                found = True
                id_ = i.split()[4]
                id_w = subprocess.run(['xprop', '-id', id_], stdout=subprocess.PIPE)
                break
        if not found:
            return wm_class, wm_name
        id_w_stdout = id_w.stdout.decode('utf-8').split('\n')
        buff = []
        for j in id_w_stdout:
            buff.append(j)

        wm_name = FocusTracker.get_wm_name(buff, wm_name)
        wm_class = FocusTracker.get_wm_class(buff, wm_class)

        wm_name = wm_name.removesuffix("\"").removeprefix("\"")
        wm_class = wm_class.removesuffix("\"").removeprefix("\"")
        return wm_class, wm_name


    def is_working(self, wm_class, wm_name):
        wm_class = wm_class.lower()
        wm_name = wm_name.lower()
        for item in self.working_list:
            cls = item['class'].lower()
            if re.search(cls, wm_class) == None:
                continue

            # We found thbe matching class
            if "name" not in item:
                # and it allows all wm names
                return True
            # else we check the wm_name is in the allowed name list
            names = item['name']
            return any(re.search(name, wm_name.lower()) != None for name in names)
        return False


    def track_focused_window(self, wm_class, wm_name, secs):
        working = self.is_working(wm_class, wm_name)

        if wm_class not in self.apps:
            self.apps[wm_class] = FocusTracker.App(wm_class)
        self.apps[wm_class].track(wm_name, secs, working)

        if working:
            self.working_hour += secs
            self.working_after_last_report += secs
        else:
            self.playing_hour += secs
            self.playing_after_last_report += secs


    def get_elapsed_time(self):
        now = datetime.datetime.now()
        duration = now - self.last_track
        self.last_track = now
        return duration


    def track_focus(self):
        self.notify("Focus tracker", "start tracking focus")
        while not self.stopping:
            wm_class, wm_name = self.get_active_window_title()
            elapsed = self.get_elapsed_time()
            self.track_focused_window(wm_class, wm_name, elapsed.total_seconds())
            time.sleep(self.duration)
        self.notify("Focus tracker", "stop tracking focus")


    def run(self):
        if self.state != FocusTracker.idle:
            return
        self.start = datetime.datetime.now()
        self.state = FocusTracker.tracking
        self.stopping = False
        self.track_focus()


    def stop(self):
        self.stopping = True
        self.start = None
        self.state = FocusTracker.idle


    def reset(self):
        self._reset()


class PomodoroTimer(Notifier):
    idle = 0
    resting = 1
    # Working should be the last as I encode the round into self.state
    working = 2

    def __init__(self):
        self.round_per_session = 2
        self.rest_time_in_session = 5
        self.rest_time_after_session = 20
        self.working_time = 30
        self._reset()


    def _reset(self):
        self.state = PomodoroTimer.idle


    def round(self):
        return self.state - PomodoroTimer.working if self.state >= PomodoroTimer.working else self.round_per_session


    def arm_timer(self, time_mins, callback):
        self.date_timer_armed = datetime.datetime.now()
        self.timer = threading.Timer(time_mins * 60, callback)
        self.timer.start()


    def start_resting(self):
        current_round = self.round()
        self.state += 1
        next_round = current_round + 1

        if next_round % self.round_per_session == 0:
            rest_time = self.rest_time_after_session
            message = "Session done."
        else:
            rest_time = self.rest_time_in_session
            message = "Round {} done.".format(current_round)
        message += " Resting for {} mins.".format(rest_time)

        self.notify("Start resting", message)
        self.arm_timer(rest_time, self.start_round)


    def start_round(self):
        round = self.round()
        self.notify("Start working", "Round {} for {} mins".format(round, self.working_time))
        self.arm_timer(self.working_time, self.start_resting)


    def run(self):
        if not self.state == PomodoroTimer.idle:
            return
        self.state = PomodoroTimer.working
        self.start_round()


    def stop(self):
        if self.state == PomodoroTimer.idle:
            return
        if self.timer != None and self.timer.is_alive():
            self.timer.cancel()
            self.date_timer_armed
            self.timer = None
        self._reset()


    def reset(self):
        was_running = self.state >= PomodoroTimer.working
        self.stop()
        self._reset()
        if was_running:
            self.run()


    def report(self):
        state = self.state if self.state <= PomodoroTimer.working else PomodoroTimer.working
        state_texts = ["idle", "resting", "working"]
        res = {"state": state_texts[state]}
        if state != PomodoroTimer.idle:
            elapsed = datetime.datetime.now() - self.date_timer_armed
            res |= {"round": self.round(), "elapsed": elapsed.__str__()}
        return res


class WorkingHourManager(Notifier):
    def __init__(self, working_list, report_each_hour):
        self.focus_tracker = FocusTracker(working_list=working_list)
        self.pomodoro_timer = PomodoroTimer()
        self.working_list = working_list
        self.report_each_hour = report_each_hour


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
        self.report_timer = threading.Timer(sleep, self._report_timer_callback)
        self.report_timer.start()


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

        if self.report_timer:
            self.report_timer.cancel()
            self.report_timer = None


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
        msg = "Starting     :  {}\n".format(focus['start_raw'].strftime(fmt)) + \
              "Total   time :  {}\n".format(self._time_format(focus['total'])) + \
              "Working time :  {} ({})\n".format(self._time_format(focus['working']), self._time_format(focus['working after last report'])) + \
              "Playing time :  {} ({})\n".format(self._time_format(focus['playing']), self._time_format(focus['playing after last report']))
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
