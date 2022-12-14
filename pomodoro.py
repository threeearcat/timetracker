import datetime
import threading

from idletracker import IdleTracker
from notifier import Notifier


class PomodoroTimer(Notifier):
    class State:
        idle = 0
        resting = 1
        # Working should be the last as I encode the round into self.state
        working = 2

    def _load_config(self, config):
        self.round_per_session = config["round_per_session"]
        self.rest_time_in_session = config["rest_time_in_session"]
        self.rest_time_after_session = config["rest_time_after_session"]
        self.working_time = config["working_time"]
        self.idle_threshold = config["idle_threshold"]

    def __init__(self, config):
        self._load_config(config)
        self.idle_tracker = IdleTracker()
        self._reset()

    def _reset(self):
        self.state = PomodoroTimer.State.idle

    def round(self):
        return (
            self.state - PomodoroTimer.State.working
            if self.state >= PomodoroTimer.State.working
            else self.round_per_session
        )

    def arm_timer(self, time_mins, callback):
        idle_time = self.idle_tracker.get_idle_time()
        if idle_time > self.idle_threshold:
            self.notify("Pomodoro timer", "Idle for a long time. Stop working")
            self._stop()
            return
        self.date_timer_armed = datetime.datetime.now()
        self.timer = threading.Timer(time_mins * 60, callback)
        self.timer.start()

    def start_resting(self):
        current_round = self.round()
        self.state += 1
        next_round = current_round + 1

        if self.round_per_session != 0 and next_round % self.round_per_session == 0:
            rest_time = self.rest_time_after_session
            message = "Session done."
        else:
            rest_time = self.rest_time_in_session
            message = "Round {} done.".format(current_round)
        message += " Resting for {} mins.".format(rest_time)

        self.notify("Pomodoro timer", "Start resting. " + message)
        self.arm_timer(rest_time, self.start_round)

    def start_round(self):
        round = self.round()
        self.notify(
            "Pomodoro timer",
            "Start working. Round {} for {} mins".format(round, self.working_time),
        )
        self.arm_timer(self.working_time, self.start_resting)

    def run(self):
        if not self.state == PomodoroTimer.State.idle:
            return
        self.state = PomodoroTimer.State.working
        self.start_round()

    def _stop(self):
        if self.timer != None and self.timer.is_alive():
            self.timer.cancel()
            self.timer = None
        self._reset()

    def stop(self):
        if self.state == PomodoroTimer.State.idle:
            return
        self.notify("Pomodoro timer", "Stop working")
        self._stop()

    def reset(self):
        was_running = self.state >= PomodoroTimer.State.working
        self.stop()
        self._reset()
        if was_running:
            self.run()

    def report(self):
        state = (
            self.state
            if self.state <= PomodoroTimer.State.working
            else PomodoroTimer.State.working
        )
        state_texts = ["idle", "resting", "working"]
        res = {"state": state_texts[state]}
        if state != PomodoroTimer.State.idle:
            elapsed = datetime.datetime.now() - self.date_timer_armed
            res |= {"round": self.round(), "elapsed": elapsed.__str__()}
        return res
