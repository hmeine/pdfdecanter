import numpy
from dynqt import QtCore, QtGui, array2qimage

UNSEEN_OPACITY = 0.5

class Slide(object):
    __slots__ = ('_size', '_header', '_footer', '_frames')
    
    def __init__(self, size):
        self._size = size
        self._header = self._footer = None
        self._frames = []

    def size(self):
        return self._size

    def __len__(self):
        return len(self._frames)

    def setHeader(self, patches):
        self._header = patches

    def header(self):
        return self._header

    def setFooter(self, patches):
        self._footer = patches

    def footer(self):
        return self._footer

    def contentRect(self, margin = 0):
        header_rect = self._header.boundingRect()
        header_rect = self._header.boundingRect()
        result = QtCore.QRectF(0, header_rect.bottom() + 1,
                               self._size.width(), self._footer.top() - (header_rect.bottom() + 1))
        if margin:
            result.adjust(margin, margin, -margin, -margin)
        return result

    def addFrame(self, patches):
        self._frames.append(patches)

    def frame(self, frameIndex):
        return self._frames[frameIndex]

    def pixelCount(self):
        result = 0
        for frame in self._frames:
            for pos, patch in frame:
                result += patch.width() * patch.height()
        return result


class Presentation(list):
    FORMAT_VERSION = 2


class Patches(list):
    __slots__ = ()
    
    def boundingRect(self):
        result = QtCore.QRect()
        for r in self:
            result |= r
        return result


class SlideRenderer(QtCore.QObject):
    DEBUG = False # True
        
    def __init__(self, slide, parentItem, parent = None):
        QtCore.QObject.__init__(self, parent)
        self._slide = slide
        self._items = {}
        self._currentFrame = None
        self._slideItem = QtGui.QGraphicsWidget(parentItem)
        self._backgroundItem()
        self._contentItem = QtGui.QGraphicsWidget(self._slideItem)
        self._navigationItem = QtGui.QGraphicsWidget(self._slideItem)
        self._coverItem().setOpacity(1.0 - UNSEEN_OPACITY)

    def slide(self):
        return self._slide

    def _slideRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._slide.size())

    def _rectItem(self, color, key):
        result = self._items.get(key, None)
        
        if result is None:
            result = QtGui.QGraphicsRectItem(self._slideRect(), self._slideItem)
            result.setBrush(color)
            result.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            self._items[key] = result

        return result

    def _backgroundItem(self):
        return self._rectItem(QtCore.Qt.white if not self.DEBUG else QtCore.Qt.red, key = 'bg')

    def _coverItem(self):
        result = self._rectItem(QtCore.Qt.black, key = 'cover')
        result.setZValue(1000)
        return result

    def frameItem(self, frameIndex):
        result = self._items.get(frameIndex, None)
        
        if result is None:
            if frameIndex == 'header':
                patches = self._slide.header() or ()
                parentItem = self._navigationItem
                zValue = 50
            elif frameIndex == 'footer':
                patches = self._slide.footer() or ()
                parentItem = self._navigationItem
                zValue = 50
            else:
                patches = self._slide.frame(frameIndex)
                parentItem = self._contentItem
                zValue = 100 + frameIndex

            result = QtGui.QGraphicsWidget(parentItem)

            for pos, patch in patches:
                pixmap = QtGui.QPixmap.fromImage(patch)
                pmItem = QtGui.QGraphicsPixmapItem(result)
                pmItem.setPos(QtCore.QPointF(pos))
                pmItem.setPixmap(pixmap)
                pmItem.setTransformationMode(QtCore.Qt.SmoothTransformation)
                pmItem.setZValue(zValue)

            self._items[frameIndex] = result

        return result

    def navigationItem(self):
        return self._navigationItem

    def slideItem(self):
        if self._currentFrame is None:
            return self.showFrame()
        return self._slideItem

    def contentItem(self):
        return self._contentItem

    def addCustomContent(self, item, frameIndex = 0):
        self._items['custom'] = self._items.get('custom', []) + [item]

        if frameIndex is None:
            frameIndex = len(self._slide)
        while frameIndex >= len(self._slide):
            self._slide.addFrame([])

        parent = self.frameItem(frameIndex)
        parent.setVisible(frameIndex <= self._currentFrame)
        item.setParentItem(parent)

    def uncover(self, seen = True):
        self._coverItem().setVisible(not seen)

    def showFrame(self, frameIndex = 0):
        result = self._slideItem

        self.frameItem('header')
        self.frameItem('footer')

        self._currentFrame = frameIndex

        for i in range(0, self._currentFrame + 1):
            item = self.frameItem(i)
            item.setVisible(True)
            if self.DEBUG:
                item.setOpacity(0.5 if i < frameIndex else 1.0)

        for i in range(frameIndex + 1, len(self._slide)):
            if i in self._items:
                self._items[i].setVisible(False)

        return result

    def currentFrame(self):
        return self._currentFrame


def changed_rects(a, b):
    changed = (b != a).any(-1)
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


def decompose_slide(rects, header_bottom, footer_top):
    header = Patches()
    if rects[0].bottom() < header_bottom:
        header.append(rects[0])
        del rects[0]

    footer = Patches()
    while len(rects):
        if rects[-1].top() < footer_top:
            break
        r = rects[-1]
        footer.append(r)
        del rects[-1]
        # if r.height() < 10 and r.width() > frame_size.width() * .8:
        #     # separator line detected
        #     break
    
    return header, rects, footer


def extractPatches(frame, rects):
    patches = Patches()
    for r in rects:
        x1, y1 = r.x(), r.y()
        x2, y2 = r.right() + 1, r.bottom() + 1
        patches.append((r.topLeft(), array2qimage(frame[y1:y2,x1:x2])))
    return patches


def detectBackground(raw_frames, useFrames = 15):
    if len(raw_frames) <= useFrames:
        sample_frames = raw_frames
    else:
        sample_frames = raw_frames[1::len(raw_frames)/useFrames]

    h, w = raw_frames[0].shape[:2]
    candidates = []
    candidates.append(sample_frames[0])
    weights = [numpy.ones((h, w), numpy.uint8)]
    
    for i in range(1, len(sample_frames)):
        print "analyzing background sample frame %d / %d..." % (i + 1, len(sample_frames))
        todo = numpy.ones((h, w), bool)
        for j in range(len(candidates)):
            # find pixels that are still 'todo' among the candidates:
            same = (sample_frames[i] == candidates[j]).all(-1) * todo
            # increase weight of candidate:
            weights[j] += same
            # stop search for those pixels:
            todo -= same
            if not numpy.any(todo):
                break
        if numpy.any(todo) and len(candidates) < 12:
            candidates.append(sample_frames[i] * todo[...,None])
            weights.append(todo.astype(numpy.uint8))
    
    weights = numpy.asarray(weights)
    candidates = numpy.asarray(candidates)
    maxpos = numpy.argmax(weights, 0)
    canvas = numpy.choose(maxpos[...,None], candidates)
    return canvas


def stack_frames(raw_frames):
    frame_size = QtCore.QSizeF(raw_frames[0].shape[1], raw_frames[0].shape[0])
    header_rows = frame_size.height() * 11 / 48

    canvas = numpy.ones_like(raw_frames[0]) * 255

    background = detectBackground(raw_frames)
    rects = changed_rects(canvas, background)
    header, content, footer = decompose_slide(
        rects, frame_size.height() / 3, frame_size.height() * 0.75)
    #assert not content, "could not find header/footer ranges"

    it = iter(raw_frames)
    frame1 = canvas

    slides = Presentation()
    slides.background = background
    slides.header_rect = header.boundingRect()
    slides.footer_rect = footer.boundingRect()

    prev_header = None

    for frame2 in it:
        changed = changed_rects(frame1, frame2)
        content = changed_rects(canvas, frame2)

        header, content, footer = decompose_slide(
            content, slides.header_rect.bottom() * 1.3, slides.footer_rect.top())

        # TODO: handle case of full-screen overlay (e.g. slide 10/11 of FATE_Motivation)?
        # (currently, goes as new slide because the header is hit)

        isNewSlide = True
        if header and header == prev_header:
            isNewSlide = False
            for r in changed:
                if r.intersects(slides.header_rect):
                    isNewSlide = True
                    break

        if isNewSlide:
            s = Slide(frame_size)
            s.setHeader(extractPatches(frame2, header))
            s.setFooter(extractPatches(frame2, footer))
            s.addFrame(extractPatches(frame2, content))
            slides.append(s)
        else:
            slides[-1].addFrame(extractPatches(frame2, changed))

        frame1 = frame2
        prev_header = header

    return slides
