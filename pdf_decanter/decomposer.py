"""Module containing code for decomposing frames into page components,
i.e. creating a Presentation instance from a sequence of images."""

import numpy, sys, time
from dynqt import QtCore, array2qimage
#import alpha

from presentation import ObjectWithFlags, Patch, Frame, Presentation

class ChangedRect(ObjectWithFlags):
    """Represents changes, i.e. a bounding box (rect()) and a number of labels within that ROI."""
    
    __slots__ = ('_rect', '_labels', '_labelImage', '_originalImage')

    def __init__(self, rect, labels, labelImage, originalImage):
        super(ChangedRect, self).__init__()
        self._rect = rect
        self._labels = labels
        self._labelImage = labelImage
        self._originalImage = originalImage

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

    def changed(self):
        """Return mask array with changed pixels set to True."""
        result = numpy.zeros((self._rect.height(), self._rect.width()), dtype = bool)
        labelROI = self.labelROI()
        for l in self._labels:
            result |= (labelROI == l)
        return result

    def image(self):
        """Returns RGBA QImage with only the changed pixels non-transparent."""
        rgb = self.subarray(self._originalImage)
        alpha = numpy.uint8(255) * self.changed()
        return array2qimage(numpy.dstack((rgb, alpha)))

    def isSuccessorOf(self, other):
        """Return whether this ChangedRect is likely to be the
        'successor' of the given other one.  This is assumed to be the
        case if both cover exactly the same pixels."""
        return self.rect() == other.rect() and numpy.all(self.changed() == other.changed())

    def __or__(self, other):
        """Return union of this and other ChangedRect.  (Both must belong to the same image & labelImage.)"""
        assert self._labelImage is other._labelImage
        assert self._originalImage is other._originalImage
        return ChangedRect(
            self._rect | other._rect,
            self._labels + other._labels,
            self._labelImage,
            self._originalImage)


def join_close_rects(rects):
    dx, dy = 10, 3
    # heuristic that penalizes the cost of extra rects/objects
    # (area of unchanged pixels included in joint rect):
    pixel_threshold = 800

    origCount = len(rects)
    
    result = []
    while rects:
        r = rects.pop()
        bigger = r.rect().adjusted(-dx, -dy, dx, dy)

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
                    bigger = r.rect().adjusted(-dx, -dy, dx, dy)
                    changed = True
                else:
                    rest.append(other)
            rects = rest

        result.append(r)

    #print 'join_close_rects: returning %d/%d rects' % (len(result), origCount)
    if origCount > len(result):
        return join_close_rects(result)

    return result


def changed_rects_numpy_only(changed, original):
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
        labelImage[y1:y2] *= (i + 1)
        result.append(ChangedRect(rect, labels, labelImage, original))

    return result


def changed_rects_ndimage(changed, original):
    labelImage, cnt = scipy.ndimage.measurements.label(changed)
    
    result = []
    for i, (y, x) in enumerate(scipy.ndimage.measurements.find_objects(labelImage, cnt)):
        rect = QtCore.QRect(x.start, y.start,
                            x.stop - x.start, y.stop - y.start)
        labels = [i + 1]
        result.append(ChangedRect(rect, labels, labelImage, original))

    return result


try:
    import scipy.ndimage
    changed_rects = changed_rects_ndimage
except ImportError:
    sys.stderr.write("WARNING: Could not import scipy.ndimage.  Falling back to suboptimal numpy-only code.\n")
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

        header_bottom = frame_size.height() * 0.16 # frame_size.height() / 3
        footer_top    = frame_size.height() * 0.75

        content = sorted(frame.content(),
                         key = lambda patch: patch.topLeft().y())
        
        for patch in content:
            rect = patch.rect()

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
            rect = patch.rect()

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

    result = []
    for page in raw_pages:
        changed = (canvas != page).any(-1)
        rects = changed_rects(changed, page)

        #occurences = collect_occurences(rects)
        rects = join_close_rects(rects)

        h, w = page.shape[:2]
        result.append(Frame(QtCore.QSizeF(w, h), rects))

    return result


def extract_patches(rects, cache = None):
    """Extract patches from the page image.
    Expects a list of ChangedRects and an optional cache dict."""
    
    patches = []
    for r in rects:
        pos = r.topLeft()
        image = r.image()
        patch = Patch(pos, image)
        patch._flags = r._flags

        if cache is not None:
            # reuse existing Patch if it has the same key:
            key = patch.key()
            patch = cache.get(key, patch)
            cache[key] = patch

        patches.append(patch)

    return patches


def decompose_pages(pages, infos = None):
    frames = create_frames(pages)
    detect_navigation(frames)
    result = Presentation(infos)

    rawPatchCount = 0
    cache = {}
    for frame in frames:
        content = frame.content()
        rawPatchCount += len(content)
        content[:] = extract_patches(content, cache)

    # could alternatively be done before filtering duplicates, but this is faster:
    result.addFrames(frames)
        
    print "%d slides, %d frames, %d distinct patches (of %d)" % (
        result.slideCount(), result.frameCount(), len(cache), rawPatchCount)
    return result
