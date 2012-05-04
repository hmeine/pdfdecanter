import numpy
from dynqt import QtCore, QtGui, qtSignal, array2qimage, rgb_view

UNSEEN_OPACITY = 0.5

class Slide(object):
    __slots__ = ('_size', '_header', '_footer', '_frames', '_pdfInfos')
    
    def __init__(self, size):
        self._size = size
        self._header = self._footer = None
        self._frames = []

        self._pdfInfos = None

    def size(self):
        return self._size

    def __len__(self):
        return len(self._frames)

    def __getitem__(self, frameIndex):
        return self.frame(frameIndex)

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
        footer_rect = self._footer.boundingRect()
        result = QtCore.QRectF(0, header_rect.bottom() + 1,
                               self._size.width(), footer_rect.top() - (header_rect.bottom() + 1))
        if margin:
            result.adjust(margin, margin, -margin, -margin)
        return result

    def addFrame(self, patches):
        self._frames.append(patches)

    def frame(self, frameIndex):
        return self._frames[frameIndex]

    def setPDFInfos(self, infos):
        if infos:
            assert len(infos) == len(self)
        self._pdfInfos = infos

    def linkAt(self, frameIndex, pos):
        if not self._pdfInfos or frameIndex >= len(self._pdfInfos):
            return None
        
        relPos = (pos.x() / self._size.width(),
                  (self._size.height() - pos.y()) / self._size.height())
        for rect, link in self._pdfInfos.relativeLinks(frameIndex):
            if numpy.all((relPos >= rect[0]) * (relPos <= rect[1])):
                return link
        return None

    def pixelCount(self):
        result = 0
        for frame in self._frames:
            for pos, patch in frame:
                result += patch.width() * patch.height()
        return result

    def __getstate__(self):
        def serializePatches(patches):
            return [((pos.x(), pos.y()), rgb_view(patch).copy())
                    for pos, patch in patches]
        return ((self._size.width(), self._size.height()),
                serializePatches(self._header) if self._header else None,
                serializePatches(self._footer) if self._footer else None,
                map(serializePatches, self._frames),
                self._pdfInfos)

    def __setstate__(self, state):
        def deserializePatches(patches):
            return Patches((QtCore.QPoint(x, y), array2qimage(patch))
                           for (x, y), patch in patches)
        (w, h), header, footer, frames, infos = state
        self._size = QtCore.QSizeF(w, h)
        self._header = header and deserializePatches(header)
        self._footer = footer and deserializePatches(footer)
        self._frames = map(deserializePatches, frames)
        self._pdfInfos = infos


class Presentation(list):
    FORMAT_VERSION = 2

    def __getnewargs__(self):
        return (list(self), )

    def __getstate__(self):
        return False # don't call __setstate__

    def __setstate__(self, state):
        assert not state # should not be called anyhow
        return


def boundingRect(rects):
    result = QtCore.QRect()
    for r in rects:
        result |= r
    return result


class Patches(list):
    __slots__ = ()
    
    def boundingRect(self):
        return boundingRect(QtCore.QRect(pos, patch.size())
                            for pos, patch in self)


class SlideRenderer(QtGui.QGraphicsWidget):
    DEBUG = False # True

    linkClicked = qtSignal(QtCore.QVariant)
        
    def __init__(self, slide, parentItem):
        QtGui.QGraphicsWidget.__init__(self, parentItem)
        self._slide = slide
        self.setGeometry(QtCore.QRectF(QtCore.QPointF(0, 0), slide.size()))
        #self.setFlag(QtGui.QGraphicsItem.ItemIsMovable)
        self.setFlag(QtGui.QGraphicsItem.ItemIsSelectable)

        self._currentFrame = None
        self._seen = False
        self._frameCallbacks = []

        self._items = {}

        self.showFrame()

    def slide(self):
        return self._slide

    def _setupItems(self):
        self._backgroundItem()

        contentItem = QtGui.QGraphicsWidget(self)
        contentItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self._items['content'] = contentItem

        navigationItem = QtGui.QGraphicsWidget(self)
        navigationItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self._items['navigation'] = navigationItem

        self.frameItem('header')
        self.frameItem('footer')

        self._coverItem()

    def _slideRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._slide.size())

    def _rectItem(self, color, key):
        result = self._items.get(key, None)
        
        if result is None:
            result = QtGui.QGraphicsRectItem(self._slideRect(), self)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            result.setBrush(color)
            result.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            self._items[key] = result

        return result

    def _backgroundItem(self):
        return self._rectItem(QtCore.Qt.white if not self.DEBUG else QtCore.Qt.red, key = 'bg')

    def _coverItem(self):
        result = self._rectItem(QtCore.Qt.black, key = 'cover')
        result.setZValue(1000)
        result.setOpacity(1.0 - UNSEEN_OPACITY)
        result.setVisible(not self._seen)
        return result

    def frameItem(self, frameIndex):
        result = self._items.get(frameIndex, None)
        
        if result is None:
            if frameIndex == 'header':
                patches = self._slide.header() or ()
                parentItem = self._items['navigation']
                zValue = 50
            elif frameIndex == 'footer':
                patches = self._slide.footer() or ()
                parentItem = self._items['navigation']
                zValue = 50
            else:
                patches = self._slide.frame(frameIndex)
                parentItem = self._items['content']
                zValue = 100 + frameIndex

            result = QtGui.QGraphicsWidget(parentItem)
            result.setZValue(zValue)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)

            for pos, patch in patches:
                pixmap = QtGui.QPixmap.fromImage(patch)
                pmItem = QtGui.QGraphicsPixmapItem(result)
                pmItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                pmItem.setPos(QtCore.QPointF(pos))
                pmItem.setPixmap(pixmap)
                pmItem.setTransformationMode(QtCore.Qt.SmoothTransformation)

            self._items[frameIndex] = result

        return result

    def mousePressEvent(self, event):
        link = self._slide.linkAt(self._currentFrame, event.pos())
        if link is not None:
            self.linkClicked.emit(link)
            event.accept()
        else:
            QtGui.QGraphicsWidget.mousePressEvent(self, event)

    def navigationItem(self):
        return self._items['navigation']

    def contentItem(self):
        return self._items['content']

    def addCustomContent(self, items, frameIndex = 0):
        """Add given custom items to the SlideRenderer, for the given
        frameIndex.  If frameIndex is larger than the currently
        largest valid index, new frames will be added accordingly.  If
        frameIndex is None, it defaults to len(slide()),
        i.e. appending one new frame."""

        # add items:
        customItems = self.customItems()
        customItems.extend(items)
        self._items['custom'] = customItems

        # add (empty) frames to corresponding Slide class if necessary:
        if frameIndex is None:
            frameIndex = len(self._slide)
        while frameIndex >= len(self._slide):
            self._slide.addFrame([])

        # set parent of custom items:
        parent = self.frameItem(frameIndex)
        parent.setVisible(frameIndex <= self._currentFrame)
        for item in items:
            item.setParentItem(parent)

    def customItems(self):
        return self._items.get('custom', [])

    def addCustomCallback(self, cb):
        """Register callback for frame changes.  Expects callable that
        will be called with two arguments: the SlideRenderer (which
        can be queried for the currentFrame()) and the new frameIndex
        that is about to become the currentFrame().

        TODO: Call with None if slide becomes invisible/inactive."""
        self._frameCallbacks.append(cb)
        if self._currentFrame is not None:
            cb(self, self._currentFrame)

    def uncover(self, seen = True):
        self._seen = seen
        self._coverItem().setVisible(not seen)

    def showFrame(self, frameIndex = 0):
        if not self._items:
            self._setupItems()

        for cb in self._frameCallbacks:
            cb(self, frameIndex)

        self._currentFrame = frameIndex

        for i in range(0, self._currentFrame + 1):
            item = self.frameItem(i)
            item.setVisible(True)
            if self.DEBUG:
                item.setOpacity(0.5 if i < frameIndex else 1.0)

        for i in range(frameIndex + 1, len(self._slide)):
            if i in self._items:
                self._items[i].setVisible(False)

        return self

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
    header = []
    if rects[0].bottom() < header_bottom:
        header.append(rects[0])
        del rects[0]

    footer = []
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
        inc = len(raw_frames)/useFrames
        end = 1 + inc * useFrames
        sample_frames = raw_frames[1:end:inc]

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
    slides.header_rect = boundingRect(header)
    slides.footer_rect = boundingRect(footer)

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
