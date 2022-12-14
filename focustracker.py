import datetime
import re
import subprocess
import threading
import time

import focusicon
from idletracker import IdleTracker
from notifier import Notifier


class FocusTracker(Notifier):
    Idle = "Idle"
    UnknownForeground = "Unknown"

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
            self.details[misc] = (
                self.details[misc] + secs if misc in self.details else secs
            )
            if working:
                self.working += secs
                self.working_details[misc] = (
                    self.working_details[misc] + secs
                    if misc in self.working_details
                    else secs
                )
            else:
                self.playing += secs
                self.playing_details[misc] = (
                    self.playing_details[misc] + secs
                    if misc in self.playing_details
                    else secs
                )

        def report(self, typ="all"):
            preset = {
                "all": (self.total, self.details),
                "working": (self.working, self.working_details),
                "playing": (self.playing, self.playing_details),
            }
            if typ not in preset:
                return {}
            else:
                rep = preset[typ]
                return {"total": rep[0], "details": rep[1]}

    def _load_config(self, config):
        import json

        self.duration = config["duration"]
        self.idle_threshold = config["idle_threshold"]
        self.idle_long_threshold = config["idle_long_threshold"]
        try:
            with open(config["working_list"]) as f:
                working_list = json.load(f)
        except:
            working_list = []
        self.working_list = working_list

    def __init__(self, config):
        self._load_config(config)
        self.stopping = True
        self.idle_tracker = IdleTracker()
        self.icon = focusicon.FocusIcon()
        self.icon.run()
        self.check_new_day_timer = None
        self._new_day = False
        self._reset()

    def _reset(self):
        self.apps = {}
        self.working_hour = 0
        self.playing_hour = 0
        self.working_after_last_report = 0
        self.playing_after_last_report = 0
        self.last_track = None
        self.state = FocusTracker.idle
        self.start = None

    def report(self, typ):
        res = {}
        if self.start != None:
            res |= {"start": self.start.__str__(), "start_raw": self.start}
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
        idle_time = self.idle_tracker.get_idle_time()
        if idle_time > self.idle_threshold:
            return FocusTracker.Idle, FocusTracker.Idle

        wm_name = FocusTracker.UnknownForeground
        wm_class = FocusTracker.UnknownForeground

        root = subprocess.run(["xprop", "-root"], stdout=subprocess.PIPE)
        if root.stdout == "":
            return wm_class, wm_name

        root_stdout = root.stdout.decode("utf-8").split("\n")
        found = False
        for i in root_stdout:
            if "_NET_ACTIVE_WINDOW(WINDOW):" in i:
                found = True
                id_ = i.split()[4]
                id_w = subprocess.run(["xprop", "-id", id_], stdout=subprocess.PIPE)
                break
        if not found:
            return wm_class, wm_name
        id_w_stdout = id_w.stdout.decode("utf-8").split("\n")
        buff = []
        for j in id_w_stdout:
            buff.append(j)

        wm_name = FocusTracker.get_wm_name(buff, wm_name)
        wm_class = FocusTracker.get_wm_class(buff, wm_class)

        wm_name = wm_name.removesuffix('"').removeprefix('"')
        wm_class = wm_class.removesuffix('"').removeprefix('"')
        return wm_class, wm_name

    def is_working(self, wm_class, wm_name):
        wm_class = wm_class.lower()
        wm_name = wm_name.lower()
        for item in self.working_list:
            cls = item["class"].lower()
            if re.search(cls, wm_class) == None:
                continue

            # We found thbe matching class
            if "name" not in item:
                # and it allows all wm names
                return True
            # else we check the wm_name is in the allowed name list
            names = item["name"]
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
        duration = (
            0 if self.last_track is None else (now - self.last_track).total_seconds()
        )
        self.last_track = now
        return duration

    def track_focus(self):
        self.notify("Focus tracker", "start tracking focus")
        self.icon.show_start()
        self.stopping = False
        while not self.stopping:
            if self.new_day():
                self._reset()
            else:
                wm_class, wm_name = self.get_active_window_title()
                elapsed = self.get_elapsed_time()
                self.track_focused_window(wm_class, wm_name, elapsed)
            time.sleep(self.duration)
        self.stopping = False

    def new_day(self):
        if not self._new_day:
            return False
        idle_time = self.idle_tracker.get_idle_time()
        if idle_time > self.idle_long_threshold:
            return True
        self._new_day = False
        print("getting back to work")
        return False

    def start_new_day(self):
        print("start a new day")
        self._new_day = True

    def arm_check_new_day_timer(self):
        t = datetime.datetime.now()
        future = datetime.datetime(t.year, t.month, t.day, 7, 0)
        if t.timestamp() > future.timestamp():
            future += datetime.timedelta(days=1)
        self.check_new_day_timer = threading.Timer(
            (future - t).total_seconds(), self.start_new_day
        )
        self.check_new_day_timer.start()

    def run(self):
        if self.state != FocusTracker.idle:
            return
        self.start = datetime.datetime.now()
        self.last_track = self.start
        self.state = FocusTracker.tracking
        self.arm_check_new_day_timer()
        self.track_focus()

    def _stop(self):
        self.stopping = True
        self.start = None
        if self.check_new_day_timer != None:
            self.check_new_day_timer.cancel()
            self.check_new_day_timer = None
        self.state = FocusTracker.idle
        self.notify("Focus tracker", "stop tracking focus")
        self.icon.show_stop()

    def stop(self):
        if self.state == FocusTracker.tracking:
            self._stop()

    def reset(self):
        self._reset()
