import gi
gi.require_version('Notify', '0.7')

from gi.repository import Notify
class Notifier(object):
    def notify(self, title, msg):
        notify = Notify.Notification.new(title, msg)
        notify.show()

