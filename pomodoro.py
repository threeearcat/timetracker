import threading
import datetime

from notifier import Notifier


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
        self.notify("Pomodoro timer", "Start working. Round {} for {} mins".format(round, self.working_time))
        self.arm_timer(self.working_time, self.start_resting)


    def run(self):
        if not self.state == PomodoroTimer.idle:
            return
        self.state = PomodoroTimer.working
        self.start_round()


    def stop(self):
        if self.state == PomodoroTimer.idle:
            return
        self.notify("Pomodoro timer", "Stop working")
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
