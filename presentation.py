import numpy, sys, time
from dynqt import QtCore, QtGui, array2qimage, rgb_view

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
        header_rect = self._header and self._header.boundingRect()
        footer_rect = self._footer and self._footer.boundingRect()
        header_height = header_rect.bottom() + 1 if self._header else 0
        result = QtCore.QRectF(0, header_height,
                               self._size.width(),
                               footer_rect.top() - header_height
                               if self._footer else self._size.height())
        if margin:
            result.adjust(margin, margin, -margin, -margin)
        return result

    def maxRectAround(self, x, y):
        result = self.contentRect()
        for patches in self._frames:
            for pos, patch in patches:
                print result
                if pos.x() < x:
                    result.setRight(min(result.right(), pos.x() - 1))
                else:
                    result.setLeft(max(result.left(), pos.x() + patch.size().width()))

                if pos.y() < y:
                    result.setBottom(min(result.bottom(), pos.y() - 1))
                else:
                    result.setTop(max(result.top(), pos.y() + patch.size().height()))
        print result
        return result

    def addFrame(self, patches):
        self._frames.append(patches)

    def frame(self, frameIndex):
        return self._frames[frameIndex]

    def setPDFInfos(self, infos):
        if infos:
            assert len(infos) == len(self)
        self._pdfInfos = infos

    def linkRects(self, frameIndex, onlyExternal = True):
        if not self._pdfInfos or frameIndex >= len(self._pdfInfos):
            return

        for rect, link in self._pdfInfos.relativeLinks(frameIndex):
            if onlyExternal and isinstance(link, int):
                continue
            x1, y1 = rect[0]
            w, h = rect[1] - rect[0]
            yield (QtCore.QRectF(x1 * self._size.width(),
                                 (1 - y1 - h) * self._size.height() - 1,
                                 w * self._size.width(),
                                 h * self._size.height()),
                   link)

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
        patches = list(self._frames)
        if self._header:
            patches.append(self._header)
        if self._footer:
            patches.append(self._footer)
        for frame in patches:
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
    FORMAT_VERSION = 3

    def __init__(self, infos = None):
        self._pdfInfos = infos

    def pdfInfos(self):
        return self._pdfInfos

    def setPDFInfos(self, infos):
        self._pdfInfos = infos
        if infos:
            pageIndex = 0
            for sl in self:
                sl.setPDFInfos(infos[pageIndex:pageIndex+len(sl)])
                pageIndex += len(sl)
            assert pageIndex == infos.pageCount()

    def __getnewargs__(self):
        return (list(self), )

    def __getstate__(self):
        return (self._pdfInfos, )

    def __setstate__(self, state):
        self._pdfInfos, = state


def boundingRect(rects):
    result = QtCore.QRect()
    for r in rects:
        result |= r
    return result


class Patches(list):
    """List of (pos, patch) pairs, where pos is a QPoint and patch a
    QImage."""
    
    __slots__ = ()
    
    def boundingRect(self):
        return boundingRect(QtCore.QRect(pos, patch.size())
                            for pos, patch in self)

    @classmethod
    def extract(cls, frame, rects):
        """Extract patches from a full frame and list of rects.
        Parameters are the frame image as ndarray, and a list of
        QRects."""
        
        patches = cls()
        for r in rects:
            x1, y1 = r.x(), r.y()
            x2, y2 = r.right() + 1, r.bottom() + 1
            patches.append((r.topLeft(), array2qimage(frame[y1:y2,x1:x2])))
        return patches


class SlideRenderer(QtGui.QGraphicsWidget):
    DEBUG = False # True

    def __init__(self, slide, parentItem):
        QtGui.QGraphicsWidget.__init__(self, parentItem)
        self._slide = slide
        self.setGeometry(QtCore.QRectF(QtCore.QPointF(0, 0), slide.size()))
        #self.setFlag(QtGui.QGraphicsItem.ItemIsMovable)
        self.setFlag(QtGui.QGraphicsItem.ItemIsSelectable)

        self._currentFrame = None
        self._seen = False
        self._frameCallbacks = []
        self._linkHandler = None

        self._items = {}

        self.showFrame()

    def slide(self):
        return self._slide

    def setLinkHandler(self, linkHandler):
        self._linkHandler = linkHandler

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

            if parentItem is self._items['content']:
                for rect, link in self._slide.linkRects(frameIndex):
                    if link.startswith('file:') and link.endswith('.mng'):
                        movie = QtGui.QMovie(link[5:])
                        player = QtGui.QLabel()
                        player.setMovie(movie)
                        movie.setScaledSize(rect.size().toSize())
                        player.resize(round(rect.width()), round(rect.height()))
                        item = QtGui.QGraphicsProxyWidget(result)
                        item.setWidget(player)
                        item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                        item.setPos(rect.topLeft())
                        movie.start()

                if self.DEBUG:
                    for rect, link in self._slide.linkRects(frameIndex, onlyExternal = False):
                        linkFrame = QtGui.QGraphicsRectItem(rect, parentItem)
                        linkFrame.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                        linkFrame.setPen(QtGui.QPen(QtCore.Qt.yellow))

            self._items[frameIndex] = result

        return result

    def mousePressEvent(self, event):
        if self._linkHandler:
            link = self._slide.linkAt(self._currentFrame, event.pos())
            if link is not None:
                self._linkHandler(link)
                event.accept()
                return
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


def changed_rects_numpy_only(a, b):
    """Given two images, returns a list of QRects containing all
    regions that changed."""
    
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


def area(rect):
    return rect.width() * rect.height()


def join_close_rects(rects):
    dx, dy = 3, 3
    # each pixel takes roughly 4 additional bytes, and 320 bytes is a
    # very rough guess of the cost of extra rects/objects:
    pixel_threshold = 80

    origCount = len(rects)
    
    result = []
    while rects:
        r = rects.pop()
        bigger = r.adjusted(-dx, -dy, dx, dy)

        # as long as rect changed (got united with other), we keep
        # looking for new intersecting rects:
        changed = True
        while changed:
            changed = False
            rest = []
            for other in rects:
                joined = None
                if bigger.intersects(other):
                    joined = r | other
                    if area(joined) - (area(r) + area(other)) > pixel_threshold:
                        joined = None
                    
                if joined:
                    r = joined
                    bigger = r.adjusted(0, 0, dx, dy)
                    changed = True
                else:
                    rest.append(other)
            rects = rest

        result.append(r)

    #print 'join_close_rects: returning %d/%d rects' % (len(result), origCount)
    if origCount > len(result):
        return join_close_rects(result)

    return result


def changed_rects_skimage(a, b):
    """Given two images, returns a list of QRects containing all
    regions that changed."""
    
    import skimage.morphology, skimage.measure
    
    changed = (b != a).any(-1)
    # FIXME: the following gives a
    # ValueError: Does not understand character buffer dtype format string ('?')
    lab = skimage.morphology.label(changed)
    props = skimage.measure.regionprops(lab, properties = ['BoundingBox'])
    
    result = []
    for p in props:
        y1, x1, y2, x2 = p['BoundingBox']
        result.append(QtCore.QRect(QtCore.QPoint(x1, y1), QtCore.QPoint(x2, y2)))
    return join_close_rects(result)


def changed_rects_ndimage(a, b):
    """Given two images, returns a list of QRects containing all
    regions that changed."""
    
    import scipy.ndimage
    
    changed = (b != a).any(-1)
    lab, cnt = scipy.ndimage.measurements.label(changed)
    
    result = []
    for y, x in scipy.ndimage.measurements.find_objects(lab, cnt):
        result.append(QtCore.QRect(x.start, y.start,
                                   x.stop - x.start, y.stop - y.start))
    return join_close_rects(result)


changed_rects = changed_rects_ndimage
#changed_rects = changed_rects_numpy_only


def decompose_slide(rects, header_bottom, footer_top):
    """Separates changed rects into (header, content, footer) triple."""
    
    rects.sort(key = lambda r: r.top())

    header = Patches()
    # FIXME: this takes *at most* one item, but e.g. Niko uses chapter / title rows:
    if rects[0].bottom() < header_bottom:
		headerRect = QtCore.QRect(rects[0])
		i = 1
		while i < len(rects) and rects[i].top() < headerRect.bottom():
			headerRect |= rects[i]
			i += 1
		header.extend(rects[:i])
		del rects[:i]

    footer = []
    while len(rects):
        if rects[-1].top() < footer_top:
            break
        r = rects.pop()
        footer.append(r)
        # if r.height() < 10 and r.width() > frame_size.width() * .8:
        #     # separator line detected
        #     break
    
    return header, rects, footer


class BackgroundDetection(object):
    """Computes image with most common pixel values from given sample
    size."""

    weighted_occurences_dtype = numpy.dtype([('color', (numpy.uint8, 3)),
                                             ('_dummy', numpy.uint8),
                                             ('count', numpy.uint32)])

    def __init__(self):
        self._weighted_occurences = None
        self._frameIndices = None

    def include_frame_indices(self, fi):
        self._frameIndices = fi
        self._frameIndex = 0

    def add_frame(self, frame):
        if self._frameIndices is not None:
            include_this = (self._frameIndex in self._frameIndices)
            self._frameIndex += 1
            if not include_this:
                return
        
        h, w = frame.shape[:2]

        if self._weighted_occurences is None:
            self._weighted_occurences = numpy.zeros(
                (10, h, w), self.weighted_occurences_dtype)
            self._candidate_count = 0

        todo = numpy.ones((h, w), bool)
        done = False
        for j in range(self._candidate_count):
            if j and not numpy.any(todo):
                done = True
                break
            candidates = self._weighted_occurences[j]
            # find pixels that are still 'todo' (not found yet) among the candidates:
            same = (frame == candidates['color']).all(-1) * todo
            # increase weight of candidate:
            candidates['count'] += same
            # stop search for those pixels:
            todo -= same
        if not done and self._candidate_count < len(self._weighted_occurences):
            self._weighted_occurences[self._candidate_count]['color'] = frame
            self._weighted_occurences[self._candidate_count]['count'] = todo
            self._candidate_count += 1
            # TODO: think about pixel-wise candidate counts (some
            # pixels might still have entries with zero counts)

    def current_estimate(self):
        maxpos = numpy.argmax(self._weighted_occurences['count'], 0)
        return numpy.choose(maxpos[...,None], self._weighted_occurences['color'])


def detectBackground(raw_frames, useFrames = 15):
    bgd = BackgroundDetection()

    if len(raw_frames) > useFrames:
        inc = len(raw_frames)/useFrames
        end = 1 + inc * useFrames
        bgd.include_frame_indices(range(len(raw_frames))[1:end:inc])
    else:
        useFrames = len(raw_frames)

    t = time.clock()
    for i in range(len(raw_frames)):
        sys.stdout.write("\ranalyzing background sample frame %d / %d..." % (i + 1, len(raw_frames)))
        sys.stdout.flush()
        bgd.add_frame(raw_frames[i])
    t = time.clock() - t
    sys.stdout.write("\ranalyzing %d background sample frames took %.3gs.\n" % (useFrames, t))
    
    sys.stdout.write("\restimating background from samples...         ")
    sys.stdout.flush()
    canvas = bgd.current_estimate()
    sys.stdout.write("\restimating background from samples... done.\n")
    return canvas


def stack_frames(raw_frames):
    raw_frames = list(raw_frames)
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

    result = Presentation()
    result.background = background
    result.header_rect = boundingRect(header)
    result.footer_rect = boundingRect(footer)

    prev_header = None

    for frame2 in it:
        changed = changed_rects(frame1, frame2)
        content = changed_rects(canvas, frame2)

        header, content, footer = decompose_slide(
            content, result.header_rect.bottom() * 1.3, result.footer_rect.top())

        # TODO: handle case of full-screen overlay (e.g. slide 10/11 of FATE_Motivation)?
        # (currently, goes as new slide because the header is hit)

        isNewSlide = True
        if header and header == prev_header:
            isNewSlide = False
            for r in changed:
                if r.intersects(result.header_rect):
                    isNewSlide = True
                    break

        if isNewSlide:
            s = Slide(frame_size)
            s.setHeader(Patches.extract(frame2, header))
            s.setFooter(Patches.extract(frame2, footer))
            s.addFrame(Patches.extract(frame2, content))
            result.append(s)
        else:
            result[-1].addFrame(Patches.extract(frame2, changed))

        frame1 = frame2
        prev_header = header

    return result
