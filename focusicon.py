#!/usr/bin/env python

import threading

import pystray
from PIL import Image, ImageDraw


class FocusIcon(object):
    rgbs = [(255, 64, 64), (124, 252, 0)]

    def _create_image(size):
        image = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        return image

    def set_color(image, size, color):
        dc = ImageDraw.Draw(image)
        dc.ellipse((0, 0, size, size), fill=color, width=0)

    def create_image(self):
        rgb = FocusIcon.rgbs[self.running]
        image = FocusIcon._create_image(self.size)
        dc = ImageDraw.Draw(image)
        dc.ellipse((0, 0, self.size, self.size), fill=rgb, width=0)
        return image

    def __init__(self):
        self.running = 0
        self.size = 64
        image = self.create_image()
        self.image = image

        icon = pystray.Icon("FocusTracker", icon=image)
        self.icon = icon

    def show_start(self):
        self.running = 1
        self.update()

    def show_stop(self):
        self.running = 0
        self.update()

    def update(self):
        rgb = FocusIcon.rgbs[self.running]
        dc = ImageDraw.Draw(self.image)
        dc.ellipse((0, 0, self.size, self.size), fill=rgb, width=0)
        self.icon.icon = self.image

    def run(self):
        threading.Thread(target=self.icon.run).start()
