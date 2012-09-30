import numpy, sys, time, hashlib
from dynqt import QtCore, QtGui, array2qimage, rgb_view


def boundingRect(rects):
    result = QtCore.QRect()
    for r in rects:
        result |= r
    return result


class Patch(object):
    __slots__ = ('_pos', '_image', '_pixmap', '_flags')

    FLAG_HEADER = 1
    FLAG_FOOTER = 2

    def __init__(self, pos, image):
        self._pos = pos
        self._image = image
        self._pixmap = None
        self._flags = 0

    def setFlag(self, flag, onoff = True):
        if onoff:
            self._flags |= flag
        else:
            self._flags &= ~flag

    def flags(self):
        return self._flags

    def flag(self, flag):
        return self._flags & flag

    def pos(self):
        return self._pos

    def size(self):
        return self._image.size()

    def boundingRect(self):
        return QtCore.QRect(self.pos(), self.size())

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

    def isSuccessorOf(self, other):
        return self._pos == other._pos and self.size() == other.size()

    @classmethod
    def extract(cls, frame, rect):
        return cls(rect.topLeft(), array2qimage(rect.subarray(frame)))

    def __iter__(self):
        yield self._pos
        yield self._image

    def key(self):
        return (self.xy(), hashlib.md5(self.ndarray()).digest())

    def __getstate__(self):
        return (self.xy(), self.ndarray().copy(), self._flags)

    def __setstate__(self, state):
        (x, y), patch, self._flags = state
        self._pos = QtCore.QPoint(x, y)
        self._image = array2qimage(patch)
        self._pixmap = None


class Patches(list):
    """List of Patch instances, which are basically positioned QImage patches."""
    
    __slots__ = ()
    
    def boundingRect(self):
        return boundingRect(patch.boundingRect() for patch in self)

    @classmethod
    def extract(cls, frame, rects, cache = None):
        """Extract patches from a full frame and list of rects.
        Parameters are the frame image as ndarray, and a list of
        QRects."""
        
        patches = cls()
        for r in rects:
            patch = Patch.extract(frame, r)
            if cache is not None:
                # reuse existing Patch if it has the same key:
                key = patch.key()
                patch = cache.get(key, patch)
                cache[key] = patch
            patches.append(patch)
        return patches


class Frame(object):
    """Single frame (PDF page) with content, header, footer.  Belongs
    to a parent Slide."""

    __slots__ = ('_size', '_content', '_slide', '_pdfPageInfos')

    def __init__(self, size, contentPatches, slide = None):
        self._size = size
        self._content = contentPatches
        self._slide = slide
        self._pdfPageInfos = None

    def setSlide(self, slide):
        self._slide = slide

    def slide(self):
        return self._slide

    def header(self):
        return [patch for patch in self._content
                if patch.flag(Patch.FLAG_HEADER)]

    def footer(self):
        return [patch for patch in self._content
                if patch.flag(Patch.FLAG_FOOTER)]

    def presentation(self):
        return self._slide.presentation()

    def size(self):
        return self._size

    def backgroundColor(self):
        return QtGui.QColor(QtCore.Qt.white)

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

        frameSize = self.size()

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
        
        frameSize = self.size()
        relPos = (pos.x() / frameSize.width(),
                  (frameSize.height() - pos.y()) / frameSize.height())
        for rect, link in self._pdfPageInfos.relativeLinks():
            if numpy.all((relPos >= rect[0]) * (relPos <= rect[1])):
                return link
        return None

    def isSuccessorOf(self, other):
        for patch in other.content():
            found = patch in self._content
            if not found:
                for replacement in self._content:
                    if replacement.isSuccessorOf(patch):
                        found = True
                        break
            if not found:
                return False
        return True

    def __getnewargs__(self):
        return self._content, self._slide


class Slide(object):
    """Collection of Frames that belong together, i.e. PDF pages that
    represent transition states of the same presentation slide.  It is
    assumed that all frames have the same size."""
    
    __slots__ = ('_presentation', '_frames', '_currentSubIndex', '_seen')
    
    def __init__(self, presentation):
        self._presentation = presentation
        self._frames = []

        self._currentSubIndex = None
        self._seen = False

    def size(self):
        return self._frames[0].size()

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

    def contentRect(self, margin = 0):
        result = QtCore.QRectF(0, 0, self._size.width(), self._size.height())

        for frame in self:
            for patch in frame.header():
                r = patch.boundingRect()
                result.setTop(max(result.top(), r.bottom() + 1))

            for patch in frame.footer():
                r = patch.boundingRect()
                result.setBottom(min(result.bottom(), r.top() - 1))

        if margin:
            result.adjust(margin, margin, -margin, -margin)

        return result

    def addFrame(self, frame):
        if len(self._frames):
            assert frame.size() == self.size()
        
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
        return ((self._size.width(), self._size.height()), self._frames)

    def __setstate__(self, state):
        (w, h), frames = state
        self._size = QtCore.QSizeF(w, h)
        self._presentation = None
        self._frames = frames
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


class ChangedRect(object):
    __slots__ = ('_rect', '_labels', '_labelImage')

    def __init__(self, rect, labels, labelImage):
        self._rect = rect
        self._labels = labels
        self._labelImage = labelImage

    def rect(self):
        return self._rect

    def area(self):
        return self._rect.width() * self._rect.height()

    def topLeft(self):
        return self._rect.topLeft()

    def subarray(self, array):
        x1, y1 = self._rect.x(), self._rect.y()
        x2, y2 = self._rect.right() + 1, self._rect.bottom() + 1
        return array[y1:y2,x1:x2]

    def labelROI(self):
        return self.subarray(self._labelImage)

    def adjusted_rect(self, *args):
        return self._rect.adjusted(*args)

    def __or__(self, other):
        assert self._labelImage is other._labelImage
        return ChangedRect(
            self._rect | other._rect,
            self._labels + other._labels,
            self._labelImage)


def join_close_rects(rects):
    dx, dy = 10, 3
    # heuristic that penalizes the cost of extra rects/objects
    # (area of unchanged pixels included in joint rect):
    pixel_threshold = 800

    origCount = len(rects)
    
    result = []
    while rects:
        r = rects.pop()
        bigger = r.adjusted_rect(-dx, -dy, dx, dy)

        # as long as rect changed (got united with other), we keep
        # looking for new intersecting rects:
        changed = True
        while changed:
            changed = False
            rest = []
            for other in rects:
                joined = None
                if bigger.intersects(other.rect()):
                    joined = r | other
                    if joined.area() > r.area() + other.area() + pixel_threshold:
                        joined = None
                    
                if joined:
                    r = joined
                    bigger = r.adjusted_rect(-dx, -dy, dx, dy)
                    changed = True
                else:
                    rest.append(other)
            rects = rest

        result.append(r)

    #print 'join_close_rects: returning %d/%d rects' % (len(result), origCount)
    if origCount > len(result):
        return join_close_rects(result)

    return result


def changed_rects_numpy_only(changed):
    """Given two images, returns a list of all regions that changed.
    Every element is a (QPoint, label_list, label_image_roi) triple."""
    
    changed_row = changed.any(-1)
    toggle_rows = list(numpy.nonzero(numpy.diff(changed_row))[0] + 1)
    if changed_row[0]:
        toggle_rows.insert(0, 0)
    if changed_row[-1]:
        toggle_rows.append(len(changed_row))
    assert len(toggle_rows) % 2 == 0

    labelImage = changed.astype(numpy.uint32)

    result = []
    it = iter(toggle_rows)
    for i, (y1, y2) in enumerate(zip(it, it)):
        changed_columns, = numpy.nonzero(changed[y1:y2].any(0))
        x1, x2 = changed_columns[0], changed_columns[-1] + 1
        rect = QtCore.QRect(x1, y1, x2-x1, y2-y1)
        labels = [i + 1]
        result.append(ChangedRect(rect, labels, labelImage))

    return result


def changed_rects_ndimage(changed):
    """Given two images, returns a list of all regions that changed.
    Every element is a (QPoint, label_list, label_image_roi) triple."""
    
    labelImage, cnt = scipy.ndimage.measurements.label(changed)
    
    result = []
    for i, (y, x) in enumerate(scipy.ndimage.measurements.find_objects(labelImage, cnt)):
        rect = QtCore.QRect(x.start, y.start,
                            x.stop - x.start, y.stop - y.start)
        labels = [i + 1]
        result.append(ChangedRect(rect, labels, labelImage))

    result = join_close_rects(result)
    return result


try:
    import scipy.ndimage
    changed_rects = changed_rects_ndimage
except ImportError:
    sys.stderr.write("WARNING: Could not import scipy.ndimage.  Falling back to suboptimal numpy-only code.")
    changed_rects = changed_rects_numpy_only


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


def detect_navigation(frames):
    """Classify header and footer patches."""

    for frame in frames:
        frame_size = frame.size()

        header_bottom = frame_size.height() * 11 / 48 # frame_size.height() / 3
        footer_top    = frame_size.height() * 0.75

        content = sorted(frame.content(),
                         key = lambda patch: patch.pos().y())
        
        for patch in content:
            rect = patch.boundingRect()

            if rect.bottom() < header_bottom:
                patch.setFlag(Patch.FLAG_HEADER)
                # headerRect = QtCore.QRect(rects[0])
                # i = 1
                # while i < len(rects) and rects[i].top() < headerRect.bottom():
                #     headerRect |= rects[i]
                #     i += 1
                # header.extend(rects[:i])
                # del rects[:i]
            else:
                break

        for patch in reversed(content):
            rect = patch.boundingRect()

            if rect.top() < footer_top:
                break
            patch.setFlag(Patch.FLAG_FOOTER)
            
            # footer = []
            # while len(rects):
            #     if rects[-1].top() < footer_top:
            #         break
            #     r = rects.pop()
            #     footer.append(r)
                # if r.height() < 10 and r.width() > frame_size.width() * .8:
                #     # separator line detected
                #     break


def create_frames(raw_pages):
    raw_pages = list(raw_pages)

    canvas = numpy.ones_like(raw_pages[0]) * 255

    cache = {}

    result = []
    for page in raw_pages:
        changed = (canvas != page).any(-1)
        rects = changed_rects(changed)

        h, w = page.shape[:2]
        result.append(Frame(QtCore.QSizeF(w, h),
                            Patches.extract(page, rects, cache)))

    print "Total number of distinct patches: %d" % len(cache)
    return result

def stack_frames(frames):
#    background = detectBackground(raw_pages)

    result = Presentation()
    #result.background = background

    prevFrame = None
    for frame in frames:
        # new Slide?
        if not prevFrame or not frame.isSuccessorOf(prevFrame):
            result.append(Slide(result))

        result[-1].addFrame(frame)
        prevFrame = frame

    result._slidesChanged()
    return result
