import numpy
import qimage2ndarray
from PyQt4 import QtCore

class Slide(object):
    def __init__(self, size):
        self._size = size
        self._frames = []

    def size(self):
        return self._size

    def __nonzero__(self):
        return bool(self._frames)

    def add_frame(self, frame, rects):
        patches = []
        for r in rects:
            x1, y1 = r.x(), r.y()
            x2, y2 = r.right() + 1, r.bottom() + 1
            patches.append(qimage2ndarray.array2qimage(frame[y1:y2,x1:x2]))

        self._frames.append(zip(rects, patches))

    def pixelCount(self):
        result = 0
        for frame in self._frames:
            for r, data in frame:
                result += r.area()
        return result

def changed_rects(a, b):
    changed = (b - a).any(-1)
    changed_row = changed.any(-1)
    toggle_rows = list(numpy.nonzero(numpy.diff(changed_row))[0] + 1)
    if changed_row[0]:
        toggle_rows.insert(0, 0)
    if changed_row[-1]:
        toggle_rows.append(len(changed_row))

    result = []
    assert len(toggle_rows) % 2 == 0
    it = iter(toggle_rows)
    for y1, y2 in zip(it, it):
        changed_columns, = numpy.nonzero(changed[y1:y2].any(0))
        x1, x2 = changed_columns[0], changed_columns[-1] + 1
        result.append(QtCore.QRect(x1, y1, x2-x1, y2-y1))
    return result

def stack_frames(raw_frames):
    frame_size = QtCore.QSize(raw_frames[0].shape[1], raw_frames[0].shape[0])
    header_rows = frame_size.height() * 11 / 48

    canvas = numpy.ones_like(raw_frames[0]) * 255

    it = iter(raw_frames)
    frame1 = canvas

    slides = []

    for frame2 in it:
        rects = changed_rects(frame1, frame2)

        isNewSlide = bool(rects) and rects[0].top() < header_rows
        if isNewSlide or not slides:
            slides.append(Slide(frame_size))
            rects = changed_rects(canvas, frame2)

        slides[-1].add_frame(frame2, rects)

        frame1 = frame2

    return slides
