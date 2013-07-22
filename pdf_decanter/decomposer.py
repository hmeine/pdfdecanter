"""Module containing code for decomposing frames into page components,
i.e. creating a Presentation instance from a sequence of images."""

import numpy, sys, time
from dynqt import QtCore, array2qimage
import pdf_infos, pdf_renderer
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

    def boundingRect(self):
        return self._rect

    def area(self):
        return self._rect.width() * self._rect.height()

    def pos(self):
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
        return self.boundingRect() == other.boundingRect() and numpy.all(self.changed() == other.changed())

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
        bigger = r.boundingRect().adjusted(-dx, -dy, dx, dy)

        # as long as rect changed (got united with other), we keep
        # looking for new intersecting rects:
        changed = True
        while changed:
            changed = False
            rest = []
            for other in rects:
                joined = None
                if bigger.intersects(other.boundingRect()):
                    joined = r | other
                    if joined.area() > r.area() + other.area() + pixel_threshold:
                        joined = None
                    
                if joined:
                    r = joined
                    bigger = r.boundingRect().adjusted(-dx, -dy, dx, dy)
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


def uint32_array(rgb_or_rgba):
    """Return uint32 array representing the color values of
    `rgb_or_rgba`.  Similar to rgb_or_rgba.view(numpy.uint32), but
    will pad RGB arrays to RGBA arrays (with zeros) and reduces the
    number of dimensions by one (i.e. will compress the last
    dimension).  `rgb_or_rgba` must be an array of uint8 values, with
    RGB or RGBA values in the last dimension
    (i.e. rgb_or_rgba.shape[-1] must be 3 or 4)."""
    
    if rgb_or_rgba.shape[-1] == 3:
        rgb_or_rgba = numpy.concatenate(
            (rgb_or_rgba,
             numpy.zeros_like(rgb_or_rgba[...,0])[...,None]), -1)
    assert rgb_or_rgba.shape[-1] == 4
    result = rgb_or_rgba.view(numpy.uint32)
    assert result.shape[-1] == 1
    return result[...,0]


def most_common_color(rgb_or_rgba, inplace_ok = False):
    """Return the most common color of the input array.  `rgb_or_rgba`
    must be an array of uint8 values, with RGB or RGBA values in the
    last dimension (i.e. rgb_or_rgba.shape[-1] must be 3 or 4)."""

    raw_colors = uint32_array(rgb_or_rgba).ravel()

    if numpy.may_share_memory(raw_colors, rgb_or_rgba) and not inplace_ok:
        raw_colors = raw_colors.copy()
    raw_colors.sort()

    # numpy.nonzero(numpy.diff(raw_colors)) returns the indices of the
    # last items of each sequence, which are the indices of the
    # sequence starts minus 1, so we would have to add one. Instead,
    # we also subtract one from the outermost indices we pad with:
    counts = numpy.diff(numpy.concatenate((
        [-1], numpy.nonzero(numpy.diff(raw_colors))[0], [len(raw_colors)-1])))

    maxPos = counts.argmax()

    color_uint32 = raw_colors[counts[:maxPos].sum()]

    return numpy.array([color_uint32]).view(numpy.uint8)[:rgb_or_rgba.shape[-1]]


def detect_background_color(rgb_or_rgba, border_width = 2):
    borders = (
        rgb_or_rgba[:border_width], # top rows
        rgb_or_rgba[-border_width:], # bottom rows (excluding top)
        rgb_or_rgba[border_width:-border_width,:border_width], # left columns
        rgb_or_rgba[border_width:-border_width,-border_width:], # right columns
        )
    return most_common_color(
        numpy.concatenate([
            pixels.reshape((-1, pixels.shape[-1])) for pixels in borders]))


def create_frames(raw_pages):
    raw_pages = list(raw_pages)

    result = []
    for page in raw_pages:
        bgColor = detect_background_color(page)

        changed = (page != bgColor).any(-1)
        rects = changed_rects(changed, page)

        #occurences = collect_occurences(rects)
        rects = join_close_rects(rects)

        h, w = page.shape[:2]
        frame = Frame(QtCore.QSizeF(w, h), rects, background = bgColor)
        result.append(frame)

    return result


def extract_patches(frames):
    rawPatchCount = 0
    cache = {}
    for frame in frames:
        content = frame.content()
        rawPatchCount += len(content)

        # extract patches from the page image:
        patches = []
        for r in content:
            pos = r.pos()
            image = r.image()
            patch = Patch(pos, image)
            patch._flags = r._flags

            # reuse existing Patch if it has the same key:
            key = patch.key()
            patch = cache.get(key, patch)
            patch.addOccurrence(frame)

            patches.append(patch)

        content[:] = patches

    return rawPatchCount, len(cache)


def decompose_pages(pages, infos = None):
    frames = create_frames(pages)

    rawPatchCount, uniquePatchCount = extract_patches(frames)

    classify_navigation(frames)
    
    # could alternatively be done before filtering duplicates, but this is faster:
    result = Presentation(infos)
    result.addFrames(frames)
        
    print "%d slides, %d frames, %d distinct patches (of %d)" % (
        result.slideCount(), result.frameCount(), uniquePatchCount, rawPatchCount)
    return result


def load_presentation(pdfFilename, sizePX):
    infos = pdf_infos.PDFInfos.create(pdfFilename)

    # if infos:
    #     pageWidthInches = numpy.diff(infos.pageBoxes()[0], axis = 0)[0,0] / 72
    #     dpi = self.slideSize()[0] / pageWidthInches

    pages = pdf_renderer.renderAllPages(pdfFilename, sizePX = sizePX,
                                        pageCount = infos and infos.pageCount())
    
    return decompose_pages(pages, infos)

# --------------------------------------------------------------------

navigation_examples = dict()

def _classificationKey(patch):
    r = patch.boundingRect()
    return (r.left(), r.right(),
            r.top(), r.bottom(),
            patch.occurrenceCount())


def add_navigation_example(patch):
    navigation_examples[_classificationKey(patch)] = (
      patch.flags() & (patch.FLAG_HEADER | patch.FLAG_FOOTER))

    train_navigation_classifier()


classifier = None

def train_navigation_classifier():
    global classifier

    from sklearn.ensemble import RandomForestClassifier
    rf = RandomForestClassifier()

    rf.fit(navigation_examples.keys(), navigation_examples.values())
    
    classifier = rf


def classify_navigation(frames):
    if classifier is None:
        return _classify_navigation_fallback(frames)

    for frame in frames:
        for patch in frame.content():
            key = _classificationKey(patch)

            klass = classifier.predict([key])
            patch.setFlag(Patch.FLAG_HEADER, klass == Patch.FLAG_HEADER)
            patch.setFlag(Patch.FLAG_FOOTER, klass == Patch.FLAG_FOOTER)
            

def _classify_navigation_fallback(frames):
    """Classify header and footer patches just by vertical position."""

    #         for r in self._renderers:
    #             r.resetItems()

    # if classifier 
    
    for frame in frames:
        frame_size = frame.size()

        header_bottom = frame_size.height() * 0.16 # frame_size.height() / 3
        footer_top    = frame_size.height() * 0.75

        content = sorted(frame.content(),
                         key = lambda patch: patch.pos().y())
        
        for patch in content:
            rect = patch.boundingRect()

            if rect.bottom() < header_bottom:
                patch.setFlag(Patch.FLAG_HEADER)
            else:
                break

        for patch in reversed(content):
            rect = patch.boundingRect()

            if rect.top() < footer_top:
                break
            patch.setFlag(Patch.FLAG_FOOTER)

#def _save_classified_examples(filename):
