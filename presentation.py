import numpy, sys, time
from dynqt import QtCore, array2qimage, rgb_view


def boundingRect(rects):
    result = QtCore.QRect()
    for r in rects:
        result |= r
    return result


class Patch(object):
    def __init__(self, pos, image):
        self._pos = pos
        self._image = image

    @classmethod
    def extract(cls, frame, rect):
        x1, y1 = rect.x(), rect.y()
        x2, y2 = rect.right() + 1, rect.bottom() + 1
        return cls(rect.topLeft(), array2qimage(frame[y1:y2,x1:x2]))

    def __iter__(self):
        yield self._pos
        yield self._image


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
            patches.append(Patch.extract(frame, r))
        return patches


class Frame(object):
    """Single frame (PDF page) with content, header, footer.  Belongs
    to a parent Slide."""

    def __init__(self, contentPatches, slide = None):
        self._content = contentPatches
        self._slide = slide

    def setSlide(self, slide):
        self._slide = slide

    def content(self):
        return self._content

    def patchSet(self):
        return set(self._content)


class Slide(object):
    __slots__ = ('_size', '_frames', '_pdfInfos')
    
    def __init__(self, size):
        self._size = size
        self._frames = []

        self._pdfInfos = None

    def size(self):
        return self._size

    def __len__(self):
        return len(self._frames)

    def __getitem__(self, frameIndex):
        return self.frame(frameIndex)

    # def contentRect(self, margin = 0):
    #     header_rect = self._header and self._header.boundingRect()
    #     footer_rect = self._footer and self._footer.boundingRect()
    #     header_height = header_rect.bottom() + 1 if self._header else 0
    #     result = QtCore.QRectF(0, header_height,
    #                            self._size.width(),
    #                            footer_rect.top() - header_height
    #                            if self._footer else self._size.height())
    #     if margin:
    #         result.adjust(margin, margin, -margin, -margin)
    #     return result

    def addFrame(self, frame):
        self._frames.append(frame)
        frame.setSlide(self)

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

    def patchSet(self):
        """mostly for debugging/statistics: set of Patch objects"""
        return set.union(*[frame.patchSet() for frame in self._frames])

    def pixelCount(self):
        result = 0
        for pos, patch in self.patchSet():
            result += patch.width() * patch.height()
        return result

    def __getstate__(self):
        def serializePatches(patches):
            return [((pos.x(), pos.y()), rgb_view(patch).copy())
                    for pos, patch in patches]
        return ((self._size.width(), self._size.height()),
                [serializePatches(frame.content()) for frame in self._frames],
                self._pdfInfos)

    def __setstate__(self, state):
        def deserializePatches(patches):
            return Patches((QtCore.QPoint(x, y), array2qimage(patch))
                           for (x, y), patch in patches)
        (w, h), frames, infos = state
        self._size = QtCore.QSizeF(w, h)
        self._frames = [Frame(deserializePatches(frame), self) for frame in frames]
        self._pdfInfos = infos


class Presentation(list):
    """List of slides."""

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


# --------------------------------------------------------------------


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

    canvas = numpy.ones_like(raw_frames[0]) * 255

    background = detectBackground(raw_frames)
    rects = changed_rects(canvas, background)

    it = iter(raw_frames)
    frame1 = canvas

    result = Presentation()
    result.background = background

    for frame2 in it:
        changed = changed_rects(frame1, frame2)
        rects = changed_rects(canvas, frame2)

        isNewSlide = True

        if isNewSlide:
            result.append(Slide(frame_size))
            frame = Frame(Patches.extract(frame2, rects))
        else:
            frame = Frame(Patches.extract(frame2, changed))
        result[-1].addFrame(frame)

        frame1 = frame2

    return result
