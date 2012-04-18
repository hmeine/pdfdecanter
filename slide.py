import numpy
import qimage2ndarray
from PyQt4 import QtCore, QtGui

UNSEEN_OPACITY = 0.5

class Slide(object):
    def __init__(self, size):
        self._size = size
        self._header = self._footer = None
        self._frames = []

    def size(self):
        return self._size

    def __len__(self):
        return len(self._frames)

    def _extractPatches(self, frame, rects):
        patches = []
        for r in rects:
            x1, y1 = r.x(), r.y()
            x2, y2 = r.right() + 1, r.bottom() + 1
            patches.append((r.topLeft(), qimage2ndarray.array2qimage(frame[y1:y2,x1:x2])))
        return patches

    def setHeader(self, frame, rects):
        self._header = self._extractPatches(frame, rects)

    def header(self):
        return self._header

    def setFooter(self, frame, rects):
        self._footer = self._extractPatches(frame, rects)

    def footer(self):
        return self._footer

    def addFrame(self, frame, rects):
        self._frames.append(self._extractPatches(frame, rects))

    def frame(self, frameIndex):
        return self._frames[frameIndex]

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
        self._temporaryOffset = QtCore.QPointF(0, 0)
        self.__contentOffset = QtCore.QPointF(0, 0)

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

            if frameIndex == 'header':
                patches = self._slide.header() or ()
                zValue = 50
            elif frameIndex == 'footer':
                patches = self._slide.footer() or ()
                zValue = 50
            else:
                patches = self._slide.frame(frameIndex)
                zValue = 100 + frameIndex
            
            for pos, patch in patches:
                pixmap = QtGui.QPixmap.fromImage(patch)
                pmItem = QtGui.QGraphicsPixmapItem(self._backgroundItem())
                pmItem.setPos(QtCore.QPointF(pos))
                pmItem.setPixmap(pixmap)
                pmItem.setTransformationMode(QtCore.Qt.SmoothTransformation)
                pmItem.setZValue(zValue)
                result.append(pmItem)

            self._items[frameIndex] = result

        return result

    def _navItems(self):
        result = []
        result.extend(self._frameItems('header'))
        result.extend(self._frameItems('footer'))
        return result

    def toggleHeaderAndFooter(self):
        for i in self._navItems():
            i.setVisible(not i.isVisible())

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

    def _navOpacity(self):
        items = self._navItems()
        if items:
            return items[0].opacity()
        return 1.0

    def _setNavOpacity(self, o):
        for i in self._navItems():
            i.setOpacity(o)

    navOpacity = QtCore.pyqtProperty(float, _navOpacity, _setNavOpacity)

    def _contentOffset(self):
        return self.__contentOffset

    def _setContentOffset(self, offset):
        """move content items by offset (used to animate slide content
        independent from header and footer)"""
        for i in range(0, self._currentFrame + 1):
            patches = self._slide.frame(i)
            items = self._frameItems(i)
            
            for (pos, patch), item in zip(patches, items):
                item.setPos(QtCore.QPointF(pos) + offset
                            + self._temporaryOffset)

        self.__contentOffset = offset

    contentOffset = QtCore.pyqtProperty(QtCore.QPointF, _contentOffset, _setContentOffset)

    def setTemporaryOffset(self, offset):
        """temporarily move all slide items by offset (used to overlay
        one slide over another for animations)"""
        shift = offset - self._temporaryOffset
        for item in self.slideItem().childItems():
            item.moveBy(shift.x(), shift.y())
        self._temporaryOffset = offset

    def showFrame(self, frameIndex = 0):
        result = self._backgroundItem()

        self._frameItems('header')
        self._frameItems('footer')

        self._currentFrame = frameIndex

        for i in range(0, self._currentFrame + 1):
            for item in self._frameItems(i):
                item.setVisible(True)
                if self.DEBUG:
                    item.setOpacity(0.5 if i < frameIndex else 1.0)

        for i in range(frameIndex + 1, len(self._slide)):
            for item in self._items.get(i, ()):
                item.setVisible(False)

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
    if rects[0].bottom() < header_rows:
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

        # TODO: handle case of full-screen overlay (e.g. slide 10/11 of FATE_Motivation)?
        # (currently, goes as new slide because the header is hit)

        isNewSlide = True
        if header and header == prev_header:
            header_rect = QtCore.QRect()
            for r in header:
                header_rect |= r

            isNewSlide = False
            for r in changed:
                if r.intersects(header_rect):
                    isNewSlide = True
                    break

        if isNewSlide:
            s = Slide(frame_size)
            s.setHeader(frame2, header)
            s.setFooter(frame2, footer)
            s.addFrame(frame2, content)
            slides.append(s)
        else:
            slides[-1].addFrame(frame2, changed)

        frame1 = frame2
        prev_header = header

    return slides
