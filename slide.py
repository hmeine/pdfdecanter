import numpy
import qimage2ndarray
from PyQt4 import QtCore, QtGui

UNSEEN_OPACITY = 0.5

class Slide(object):
    def __init__(self, size):
        self._size = size
        self._frames = []

    def size(self):
        return self._size

    def __len__(self):
        return len(self._frames)

    def add_frame(self, frame, rects):
        patches = []
        for r in rects:
            x1, y1 = r.x(), r.y()
            x2, y2 = r.right() + 1, r.bottom() + 1
            patches.append((r.topLeft(), qimage2ndarray.array2qimage(frame[y1:y2,x1:x2])))

        self._frames.append(patches)

    def pixelCount(self):
        result = 0
        for frame in self._frames:
            for pos, patch in frame:
                result += patch.width() * patch.height()
        return result


class SlideRenderer(QtCore.QObject):
    DEBUG = False # True
        
    def __init__(self, slide, groupItem, parent = None):
        QtCore.QObject.__init__(self, parent)
        self._slide = slide
        self._items = {}
        self._currentFrame = None
        self._groupItem = groupItem
        self._coverItem().setOpacity(1.0 - UNSEEN_OPACITY)

    def slide(self):
        return self._slide

    def _rectItem(self, color, zValue, key):
        result = self._items.get(key, None)
        
        if result is None:
            rect = QtCore.QRect(QtCore.QPoint(0, 0), self._slide.size())
            result = QtGui.QGraphicsRectItem(QtCore.QRectF(rect), self._groupItem)
            result.setBrush(color)
            result.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            result.setZValue(zValue)
            self._items[key] = result

        return result

    def _backgroundItem(self):
        return self._rectItem(QtCore.Qt.white if not self.DEBUG else QtCore.Qt.red,
                              zValue = 10, key = 'bg')

    def _coverItem(self):
        result = self._rectItem(QtCore.Qt.black, zValue = 1000, key = 'cover')
        result.setParentItem(self._backgroundItem())
        return result

    def _frameItems(self, frameIndex):
        result = self._items.get(frameIndex, None)
        
        if result is None:
            result = []
            
            for pos, patch in self._slide._frames[frameIndex]:
                pixmap = QtGui.QPixmap.fromImage(patch)
                pmItem = QtGui.QGraphicsPixmapItem(self._backgroundItem())
                pmItem.setPos(QtCore.QPointF(pos))
                pmItem.setPixmap(pixmap)
                pmItem.setTransformationMode(QtCore.Qt.SmoothTransformation)
                pmItem.setZValue(100 + frameIndex)
                result.append(pmItem)

            self._items[frameIndex] = result

        return result

    def slideItem(self):
        if self._currentFrame is None:
            return self.showFrame()
        return self._backgroundItem()

    def uncover(self, seen = True):
        self._coverItem().setVisible(not seen)

    def _frameOpacity(self):
        return self._items[self._currentFrame][0].opacity()

    def _setFrameOpacity(self, o):
        for i in self._items[self._currentFrame]:
            i.setOpacity(o)

    frameOpacity = QtCore.pyqtProperty(float, _frameOpacity, _setFrameOpacity)

    def showFrame(self, frameIndex = 0):
        result = self._backgroundItem()

        for i in range(0, frameIndex + 1):
            for item in self._frameItems(i):
                item.setVisible(True)
                if self.DEBUG:
                    item.setOpacity(0.5 if i < frameIndex else 1.0)
        for i in range(frameIndex + 1, len(self._slide)):
            for item in self._items.get(i, ()):
                item.setVisible(False)

        self._currentFrame = frameIndex

        return result

    def currentFrame(self):
        return self._currentFrame


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


def decompose_slide(rects, frame_size):
    # detect header
    header_rows = frame_size.height() * 11 / 48

    header = []
    if rects[0].top() < header_rows:
        header.append(rects[0])
        del rects[0]

    # detect footer
    footer_rows = frame_size.height() / 5

    footer = []

    while len(rects):
        if rects[-1].top() < frame_size.height() - footer_rows:
            break
        r = rects[-1]
        footer.append(r)
        del rects[-1]
        if r.height() < 10 and r.width() > frame_size.width() * .8:
            # separator line detected
            break
    
    return header, rects, footer


def stack_frames(raw_frames):
    frame_size = QtCore.QSize(raw_frames[0].shape[1], raw_frames[0].shape[0])
    header_rows = frame_size.height() * 11 / 48

    canvas = numpy.ones_like(raw_frames[0]) * 255

    it = iter(raw_frames)
    frame1 = canvas

    slides = []

    prev_header = None

    for frame2 in it:
        changed = changed_rects(frame1, frame2)
        content = changed_rects(canvas, frame2)

        header, content, footer = decompose_slide(content, frame_size)

        isNewSlide = True
        if header and header == prev_header:
            header_rect = QtCore.QRect()
            for r in header:
                header_rect.unite(r)

            isNewSlide = False
            for r in changed:
                if r.intersects(header_rect):
                    isNewSlide = True
                    break

        if isNewSlide:
            slides.append(Slide(frame_size))
            rects = header + content + footer
        else:
            rects = changed

        slides[-1].add_frame(frame2, rects)

        frame1 = frame2
        prev_header = header

    return slides
