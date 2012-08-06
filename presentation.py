import numpy, sys, time, hashlib
from dynqt import QtCore, QtGui, array2qimage, rgb_view


def boundingRect(rects):
    result = QtCore.QRect()
    for r in rects:
        result |= r
    return result


class Patch(object):
    __slots__ = ('_pos', '_image', '_pixmap')
    
    def __init__(self, pos, image):
        self._pos = pos
        self._image = image
        self._pixmap = None

    def pos(self):
        return self._pos

    def xy(self):
        return self._pos.x(), self._pos.y()

    def ndarray(self):
        return rgb_view(self._image)

    def pixmap(self):
        if self._pixmap is None:
            self._pixmap = QtGui.QPixmap.fromImage(self._image)
        return self._pixmap

    def pixelCount(self):
        return self._image.width() * self._image.height()

    @classmethod
    def extract(cls, frame, rect):
        x1, y1 = rect.x(), rect.y()
        x2, y2 = rect.right() + 1, rect.bottom() + 1
        return cls(rect.topLeft(), array2qimage(frame[y1:y2,x1:x2]))

    def __iter__(self):
        yield self._pos
        yield self._image

    def __hash__(self):
        return hash((self.xy(),
                     hashlib.md5(self.ndarray()).digest()))

    def __cmp__(self, other):
        result = cmp(type(self), type(other)) or cmp(self.xy(), other.xy())
        if result:
            return result
        if numpy.all(self.ndarray() == other.ndarray()):
            return 0
        return cmp(self._image, other._image) # fall back to id (memory address)

    def __getstate__(self):
        return (self.xy(), self.ndarray().copy())

    def __setstate__(self, state):
        (x, y), patch = state
        self._pos = QtCore.QPoint(x, y)
        self._image = array2qimage(patch)
        self._pixmap = None


class Patches(list):
    """List of Patch instances, which are basically positioned QImage patches."""
    
    __slots__ = ()
    
    def boundingRect(self):
        return boundingRect(QtCore.QRect(pos, patch.size())
                            for pos, patch in self)

    @classmethod
    def extract(cls, frame, rects, cache = None):
        """Extract patches from a full frame and list of rects.
        Parameters are the frame image as ndarray, and a list of
        QRects."""
        
        patches = cls()
        for r in rects:
            patch = Patch.extract(frame, r)
            if cache is not None:
                # reuse existing Patch if it compares equal:
                patch = cache.get(patch, patch)
                cache[patch] = patch
            patches.append(patch)
        return patches


class Frame(object):
    """Single frame (PDF page) with content, header, footer.  Belongs
    to a parent Slide."""

    __slots__ = ('_content', '_slide', '_pdfPageInfos')

    def __init__(self, contentPatches, slide = None):
        self._content = contentPatches
        self._slide = slide
        self._pdfPageInfos = None

    def setSlide(self, slide):
        self._slide = slide

    def slide(self):
        return self._slide

    def presentation(self):
        return self._slide.presentation()

    def content(self):
        return self._content

    def patchSet(self):
        return set(self._content)

    def frameIndex(self):
        """Return frameIndex() into whole presentation()."""
        return self.presentation().frameIndex(self)

    def subIndex(self):
        """Return subIndex() into parent slide()."""
        return self.slide().index(self)

    def setPDFPageInfos(self, infos):
        self._pdfPageInfos = infos

    def linkRects(self, onlyExternal = True):
        if not self._pdfPageInfos:
            return

        frameSize = self._slide.size()

        for rect, link in self._pdfPageInfos.relativeLinks():
            if onlyExternal and isinstance(link, int):
                continue
            x1, y1 = rect[0]
            w, h = rect[1] - rect[0]
            yield (QtCore.QRectF(x1 * frameSize.width(),
                                 (1 - y1 - h) * frameSize.height() - 1,
                                 w * frameSize.width(),
                                 h * frameSize.height()),
                   link)

    def linkAt(self, pos):
        if not self._pdfPageInfos:
            return None
        
        frameSize = self._slide.size()
        relPos = (pos.x() / frameSize.width(),
                  (frameSize.height() - pos.y()) / frameSize.height())
        for rect, link in self._pdfPageInfos.relativeLinks():
            if numpy.all((relPos >= rect[0]) * (relPos <= rect[1])):
                return link
        return None



class Slide(object):
    """Collection of Frames that belong together, i.e. PDF pages that
    represent transition states of the same presentation slide.  It is
    assumed that all frames have the same size."""
    
    __slots__ = ('_size', '_presentation', '_frames', '_currentSubIndex', '_seen')
    
    def __init__(self, size, presentation):
        self._size = size
        self._presentation = presentation
        self._frames = []

        self._currentSubIndex = None
        self._seen = False

    def size(self):
        return self._size

    def presentation(self):
        return self._presentation

    def slideIndex(self):
        return self._presentation.index(self)

    def __len__(self):
        return len(self._frames)

    def __getitem__(self, subIndex):
        return self.frame(subIndex)

    def index(self, frame):
        return self._frames.index(frame)

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

    def frame(self, subIndex):
        return self._frames[subIndex]

    def currentSubIndex(self):
        return self._currentSubIndex

    def currentFrame(self):
        return self.frame(self._currentSubIndex)

    def setCurrentSubIndex(self, index):
        self._currentSubIndex = index
        # TODO: notification?

    def seen(self):
        return self._seen

    def setSeen(self, seen):
        self._seen = seen
        # TODO: notification?

    def __getstate__(self):
        return ((self._size.width(), self._size.height()),
                [frame.content() for frame in self._frames])

    def __setstate__(self, state):
        (w, h), frames = state
        self._size = QtCore.QSizeF(w, h)
        self._presentation = None
        self._frames = [Frame(frame, self) for frame in frames]
        # __init__ is not called:
        self._currentSubIndex = None
        self._seen = None


class Presentation(list):
    """List of slides."""

    def __init__(self, infos = None):
        self._pdfInfos = infos
        self._slidesChanged()

    def _slidesChanged(self):
        self._frame2Slide = []
        self._slide2Frame = []
        for i, s in enumerate(self):
            self._slide2Frame.append(len(self._frame2Slide))
            self._frame2Slide.extend([(i, j) for j in range(len(s))])
            s._presentation = self

    def pdfInfos(self):
        return self._pdfInfos

    def frameCount(self):
        return len(self._frame2Slide)

    def frames(self):
        for slide in self:
            for frame in slide:
                yield frame

    def frame(self, frameIndex):
        slideIndex, subIndex = self._frame2Slide[frameIndex]
        return self[slideIndex][subIndex]

    def frameIndex(self, frame):
        slideIndex = self.index(frame.slide())
        return self._slide2Frame[slideIndex] + frame.subIndex()

    def setPDFInfos(self, infos):
        self._pdfInfos = infos
        if infos:
            assert len(list(self.frames())) == len(infos)
            for frame, pageInfos in zip(self.frames(), infos):
                frame.setPDFPageInfos(pageInfos)

    def patchSet(self):
        """mostly for debugging/statistics: set of Patch objects"""
        return set.union(*[frame.patchSet() for frame in self.frames()])

    def pixelCount(self):
        result = 0
        for patch in self.patchSet():
            result += patch.pixelCount()
        return result

    def __getnewargs__(self):
        return (list(self), )

    def __getstate__(self):
        return (self._pdfInfos, )

    def __setstate__(self, state):
        pdfInfos, = state
        self.setPDFInfos(pdfInfos)
        self._slidesChanged()


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


def stack_frames(raw_pages):
    raw_pages = list(raw_pages)
    frame_size = QtCore.QSizeF(raw_pages[0].shape[1], raw_pages[0].shape[0])

    canvas = numpy.ones_like(raw_pages[0]) * 255

    background = detectBackground(raw_pages)
    rects = changed_rects(canvas, background)

    result = Presentation()
    result.background = background

    cache = {}

    page1 = canvas
    for page2 in raw_pages:
        changed = changed_rects(page1, page2)
        rects = changed_rects(canvas, page2)

        isNewSlide = True

        if isNewSlide:
            result.append(Slide(frame_size, result))
            frame = Frame(Patches.extract(page2, rects, cache))
        else:
            frame = Frame(Patches.extract(page2, changed, cache))
        result[-1].addFrame(frame)

        page1 = page2

    return result
