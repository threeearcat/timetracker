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
            raise OSError(f"Could not find library `{name}`")
        return ctypes.cdll.LoadLibrary(path)


class FocusTracker(object):
    IdleForeground = "Unknown"

    class App(object):
        def __init__(self, name):
            self.name = name
            self.total = 0
            self.details = {}


        def track(self, misc, secs):
            self.total += secs
            if misc not in self.details:
                self.details[misc] = 0
            self.details[misc] += secs


        def report(self):
            res = {"total": self.total, "details": self.details}
            return res


    def __init__(self):
        self.duration = 5
        self.apps = {}
        self.stopping = True
        self.last_track = datetime.datetime.now()
        self.idle_tracker = IdleTracker()
        self.idle_threshold = 180

        
    def report(self):
        res = {}
        for name, app in self.apps.items():
            res[name] = app.report()
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
        return wm_class, wm_name


    def track_focused_window(self, wm_class, wm_name, secs):
        if wm_class not in self.apps:
            self.apps[wm_class] = FocusTracker.App(wm_class)
        self.apps[wm_class].track(wm_name, secs)


    def get_elapsed_time(self):
        now = datetime.datetime.now()
        duration = now - self.last_track
        self.last_track = now
        return duration


    def track_focus(self):
        while not self.stopping:
            wm_class, wm_name = self.get_active_window_title()
            elapsed = self.get_elapsed_time()
            self.track_focused_window(wm_class, wm_name, elapsed.total_seconds())
            time.sleep(self.duration)


    def run(self):
        self.stopping = False
        self.track_focus()


    def stop(self):
        self.stopping = True


class PomodoroTimer(object):
    def __init__(self):
        pass

    def run(self):
        pass

    def stop(self):
        pass


class WorkingHourManager(object):
    def __init__(self):
        self.focus_tracker = FocusTracker()
        self.pomodoro_timer = PomodoroTimer()


    def run(self):
        threading.Thread(target=self.focus_tracker.run).start()
        threading.Thread(target=self.pomodoro_timer.run).start()


    def stop(self):
        self.focus_tracker.stop()
        self.pomodoro_timer.stop()


    def report(self):
        focus = self.focus_tracker.report()
        print(json.dumps(focus, indent=4, sort_keys=True))


    def reset(self):
        pass


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
    manager = WorkingHourManager()
    cmds = {'run': manager.run, 'stop': manager.stop, 'report': manager.report, 'reset': manager.reset}
    sock = run_server()
    while True:
        data, _ = sock.recvfrom(1024)
        cmd = data.decode("utf-8").strip()
        print(cmd)
        if cmd in cmds:
            cmds[cmd]()


if __name__ == '__main__':
    main()
