#  Copyright 2012-2014 Hans Meine <hans_meine@gmx.net>
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""Module containing code for decomposing frames into page components,
i.e. creating a Presentation instance from a sequence of images."""

import os, sys, time, hashlib, numpy
from dynqt import QtCore, QtGui, qimage2ndarray
import pdf_infos, pdf_renderer, bz2_pickle
import alpha

from presentation import ObjectWithFlags, Patch, Frame, Presentation

class MostFrequentlyUsedColors(object):
    def __init__(self):
        self._colors = []
        self._counts = []

    def __iter__(self):
        return iter(self._colors)

    def add(self, color):
        try:
            i = self._colors.index(color)
            self._counts[i] += 1
            if i > 0 and self._counts[i-1] < self._counts[i]:
                self._colors[i] = self._colors[i-1]
                self._colors[i-1] = color
                count = self._counts[i]
                self._counts[i] = self._counts[i-1]
                self._counts[i-1] = count
        except ValueError:
            self._colors.append(color)
            self._counts.append(1)

class ChangedRect(ObjectWithFlags):
    """Represents changes, i.e. a bounding box (rect()) and a number
    of labels within that ROI.  Plain rectangles are represented with
    an empty list of labels and a float QRectF."""
    
    __slots__ = ('_rect', '_labels', '_labelImage',
                 '_originalImage', '_color', '_alphaImage',
                 '_occurrences')

    def __init__(self, rect, labels, labelImage, originalImage, alphaImage, color = None):
        super(ChangedRect, self).__init__()
        self._rect = rect
        self._labels = labels
        self._labelImage = labelImage
        self._originalImage = originalImage
        self._alphaImage = alphaImage
        self._color = color
        self._occurrences = []

    def boundingRect(self):
        if not self._labels:
            return self._rect.toRect()
        return self._rect

    def area(self):
        return self._rect.width() * self._rect.height()

    def pos(self):
        return self._rect.topLeft()

    def color(self):
        return self._color
    
    def addOccurrence(self, frame):
        self._occurrences.append(frame)

    def occurrenceCount(self):
        return len(self._occurrences)
        
    def subarray(self, array):
        x1, y1, x2, y2 = self._rect.getCoords()
        return array[y1:y2+1,x1:x2+1]

    def labelROI(self):
        return self.subarray(self._labelImage)

    def changed(self):
        """Return mask array with changed pixels set to True."""
        if not self._labels:
            return None
        labelROI = self.labelROI()
        #return (labelROI[...,None] == self._labels).any(-1)
        result = (labelROI == self._labels[0])
        for l in self._labels[1:]:
            result |= (labelROI == l)
        return result

    def key(self):
        if self.flag(Patch.FLAG_RECT):
            return (self._rect.getCoords(), self._color and self._color.rgb())
        if self.flag(Patch.FLAG_MONOCHROME):
            imageData = self.subarray(self._alphaImage)
        else:
            imageData = self.subarray(self._originalImage)
        return (self._rect.x(), self._rect.y(),
                hashlib.md5(imageData.ravel()).digest(),
                self._color and self._color.rgb())

    def detectAlpha(self, bgColor = None, knownColors = MostFrequentlyUsedColors()):
        assert self._labels, "don't call with FLAG_RECT"

        rgb = self.subarray(self._originalImage)
        if bgColor is not None:
            def tryColors():
                for fgColor in knownColors:
                    yield fgColor
                fgColor = tuple(most_common_color(rgb[self.changed()]))
                if fgColor not in knownColors:
                    yield fgColor

            for fgColor in tryColors():
                alpha_channel = alpha.verified_unblend(rgb, bgColor, fgColor)
                if alpha_channel is not None:
                    knownColors.add(fgColor)
                    self._flags |= Patch.FLAG_MONOCHROME
                    r, g, b = fgColor
                    self._color = QtGui.QColor(r, g, b)
                    self.subarray(self._alphaImage)[:] = alpha_channel
                    return
        
    def image(self):
        """Returns RGBA QImage with only the changed pixels non-transparent."""
        assert self._labels, "don't call with FLAG_RECT"

        result = QtGui.QImage(self._rect.width(), self._rect.height(), QtGui.QImage.Format_ARGB32)
        if self.flag(Patch.FLAG_MONOCHROME):
            qimage2ndarray.rgb_view(result)[:] = self._color.getRgb()[:3]
            qimage2ndarray.alpha_view(result)[:] = self.subarray(self._alphaImage) * self.changed()
        else:
            qimage2ndarray.rgb_view(result)[:] = self.subarray(self._originalImage)
            qimage2ndarray.alpha_view(result)[:] = numpy.uint8(255) * self.changed()
        return result

    def isSuccessorOf(self, other):
        """Return whether this ChangedRect is likely to be the
        'successor' of the given other one.  This is assumed to be the
        case if both cover exactly the same pixels."""
        return self.boundingRect() == other.boundingRect() and numpy.all(self.changed() == other.changed())

    def isMergeCompatible(self, other):
        if not self._labels:
            return False # FLAG_RECTs are not mergeable
        return (self._occurrences == other._occurrences and
                self._labelImage is other._labelImage and
                self._originalImage is other._originalImage and
                self._alphaImage is other._alphaImage and
                self._color == other._color and
                self._flags == other._flags)

    def __ior__(self, other):
        """Return union of this and other ChangedRect.  (Both must belong to the same image & labelImage.)"""
        assert self.isMergeCompatible(other)
        self._rect |= other._rect
        self._labels.extend(other._labels)
        return self


def _area(rect):
    return rect.width() * rect.height()

FLAG_MERGED = 512  # marks rects that were merged into other ones ('delete' flag)
    
def join_close_rects(frame):
    dx, dy = 30, 3
    # heuristic that penalizes the cost of extra rects/objects
    # (area of unchanged pixels included in joint rect):
    pixel_threshold = 800

    rects = frame.content()
    origCount = len(rects)

    result = []
    while rects:
        r = rects.pop()
        if r.flag(FLAG_MERGED) or r._occurrences[0] is not frame:
            # Since _occurrences of all compatible rects is the same,
            # we don't have to try merging on other frames again.
            result.append(r)
            continue
        bbox = r.boundingRect()
        bigger = bbox.adjusted(-dx, -dy, dx, dy)

        compatible = [other for other in rects
                      if r.isMergeCompatible(other)]
        
        # as long as rect changed (got united with other), we keep
        # looking for new intersecting rects:
        changed = True
        while changed:
            changed = False
            for other in compatible:
                if other.flag(FLAG_MERGED):
                    continue
                otherBBox = other.boundingRect()
                if bigger.intersects(otherBBox):
                    joinedBBox = bbox | otherBBox
                    if _area(joinedBBox) <= _area(bbox) + _area(otherBBox) + pixel_threshold:
                        r |= other
                        other.setFlag(FLAG_MERGED)
                        bbox = r.boundingRect()
                        bigger = bbox.adjusted(-dx, -dy, dx, dy)
                        changed = True

        result.append(r)

    #print 'join_close_rects: returning %d/%d rects' % (len(result), origCount)
    if origCount > len(result):
        return join_close_rects(result)

    result = [rect for rect in result if not rect.flag(FLAG_MERGED)]

    return result


class BackgroundDetection(object):
    """Computes image with most common pixel values from given sample
    size."""

    weighted_occurrences_dtype = numpy.dtype([('color', (numpy.uint8, 3)),
                                              ('_dummy', numpy.uint8),
                                              ('count', numpy.uint32)])

    def __init__(self):
        self._weighted_occurrences = None
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

        if self._weighted_occurrences is None:
            self._weighted_occurrences = numpy.zeros(
                (10, h, w), self.weighted_occurrences_dtype)
            self._candidate_count = 0

        todo = numpy.ones((h, w), bool)
        done = False
        for j in range(self._candidate_count):
            if j and not numpy.any(todo):
                done = True
                break
            candidates = self._weighted_occurrences[j]
            # find pixels that are still 'todo' (not found yet) among the candidates:
            same = (frame == candidates['color']).all(-1) * todo
            # increase weight of candidate:
            candidates['count'] += same
            # stop search for those pixels:
            todo -= same
        if not done and self._candidate_count < len(self._weighted_occurrences):
            self._weighted_occurrences[self._candidate_count]['color'] = frame
            self._weighted_occurrences[self._candidate_count]['count'] = todo
            self._candidate_count += 1
            # TODO: think about pixel-wise candidate counts (some
            # pixels might still have entries with zero counts)

    def current_estimate(self):
        maxpos = numpy.argmax(self._weighted_occurrences['count'], 0)
        return numpy.choose(maxpos[...,None], self._weighted_occurrences['color'])


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
    result = rgb_or_rgba.view(numpy.uint32).reshape(rgb_or_rgba.shape[:-1])
    return result


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


def detect_background_color_four_borders(rgb_or_rgba, border_width = 2):
    borders = (
        rgb_or_rgba[:border_width], # top rows
        rgb_or_rgba[-border_width:], # bottom rows (excluding top)
        rgb_or_rgba[border_width:-border_width,:border_width], # left columns
        rgb_or_rgba[border_width:-border_width,-border_width:], # right columns
        )
    return most_common_color(
        numpy.concatenate([
            pixels.reshape((-1, pixels.shape[-1])) for pixels in borders]))


def detect_background_color(rgb_or_rgba, rect = None, outer_color = None):
    """Detect constant background color by looking at leftmost /
    rightmost pixels in given ROI."""
    h, w, channelCount = rgb_or_rgba.shape
    
    if rect is None:
        rect = QtCore.QRect(0, 0, w, h)

    x1, x2 = rect.left(), rect.right()
    if outer_color is not None:
        # skip potentially antialiased / partially covered pixels
        x1 += 1
        x2 -= 1
    horizontal_lines = (rgb_or_rgba[:,x1] == rgb_or_rgba[:,x2]).all(-1)

    # disregard lines that contain outer color
    if outer_color is not None:
        horizontal_lines[(rgb_or_rgba[:,x1] == outer_color).all(-1)] = False

    if not numpy.any(horizontal_lines):
        return detect_background_color_four_borders(rgb_or_rgba)
        
    return most_common_color(rgb_or_rgba[horizontal_lines,x1])


def changed_rects_ndimage(changed, original):
    labelImage, cnt = scipy.ndimage.measurements.label(changed)
    alpha = numpy.empty(original.shape[:2], dtype = numpy.uint8)
    alpha[:] = 0
    
    result = []
    for i, (y, x) in enumerate(scipy.ndimage.measurements.find_objects(labelImage, cnt)):
        rect = QtCore.QRect(x.start, y.start,
                            x.stop - x.start, y.stop - y.start)
        labels = [i + 1]
        result.append(ChangedRect(rect, labels, labelImage, original, alpha))

    return result


def create_frames(raw_pages):
    """Create preliminary Frames from raw pages.  The Frame contents
    will not be Patch instances yet, but ChangedRects."""

    raw_pages = list(raw_pages)

    result = []
    for page in raw_pages:
        bgColor = detect_background_color(page)

        changed = (page != bgColor).any(-1)
        rects = changed_rects_ndimage(changed, page)

        for r in rects:
            #if not r.flag(Patch.FLAG_RECT):
            r.detectAlpha(bgColor = bgColor)
        
        h, w = page.shape[:2]
        r, g, b = bgColor
        bgColor = QtGui.QColor(r, g, b)
        bg = ChangedRect(QtCore.QRectF(0, 0, w, h), (), None, None, None, bgColor)
        bg.setFlag(Patch.FLAG_RECT)
        frame = Frame(QtCore.QSizeF(w, h), [bg] + rects)
        result.append(frame)

    return result


try:
    import scipy.ndimage
except ImportError:
    def create_frames_not_possible(raw_pages):
        raise RuntimeError, "Could not import scipy.ndimage; frame decomposition not possible."
    create_frames = create_frames_not_possible


def find_identical_rects(frames):
    """Unify ChangedRects with identical key()s."""
    
    rawRectCount = 0
    cache = {}
    for frame in frames:
        content = frame.content()
        rawRectCount += len(content)

        uniqueContent = []
        for r in content:
            key = r.key()
            r = cache.get(key, r)
            r.addOccurrence(frame)
            cache[key] = r

            uniqueContent.append(r)

        content[:] = uniqueContent

    return rawRectCount, len(cache)


def extract_patches(frames):
    """Replace ChangedRects with Patches (in-place) within the given
    list of Frames."""

    patchMapping = {}
        
    for frame in frames:
        content = frame.content()

        patches = []
        for r in content:
            # map occurrences of same rect onto same patch:
            patch = patchMapping.get(r)
            if patch is None:
                # convert ChangedRect into Patch (extracting ROI from page image):
                pos = r.pos()
                if not r.flag(Patch.FLAG_RECT):
                    image = r.image()
                    patch = Patch(pos, image, r.occurrenceCount(), r.color())
                else:
                    assert r.color() is not None
                    patch = Patch(pos, r._rect.size(), r.occurrenceCount(), r.color())
                    assert patch.color() is not None
                patch._flags = r._flags

                patchMapping[r] = patch

            patches.append(patch)

        content[:] = patches


def decompose_pages(pages, infos = None):
    frames = create_frames(pages)

    rawPatchCount, uniquePatchCount = find_identical_rects(frames)

    for frame in frames:
        frame.content()[:] = join_close_rects(frame)
        #content[:] = join_compatible_rects(content)

    extract_patches(frames)

    classify_navigation(frames)
    
    # could alternatively be done before filtering duplicates, but this is faster:
    result = Presentation(infos)
    result.addFrames(frames)

    monochromePatchCount = sum(bool(patch.flag(Patch.FLAG_MONOCHROME))
                               for patch in result.patchSet())
    monochromeColorCount = len(set(patch.color().rgb()
                                   for patch in result.patchSet()
                                   if patch.flag(Patch.FLAG_MONOCHROME)))
        
    print "%d slides, %d frames, %d distinct patches (of %d) before merging, %d monochrome (%d colors)" % (
        result.slideCount(), result.frameCount(),
        uniquePatchCount, rawPatchCount, monochromePatchCount, monochromeColorCount)
    return result


def decompose_pdf(pdfFilename, sizePX):
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
        frameWidth  = frame.sizeF().width()
        frameHeight = frame.sizeF().height()
        for patch in frame.content():
            key = _classificationKey(patch)

            klass = classifier.predict([key])
            top, bottom = key[2:4]
            patch.setFlag(Patch.FLAG_HEADER, (klass == Patch.FLAG_HEADER) and (bottom < frameHeight / 2))
            patch.setFlag(Patch.FLAG_FOOTER, (klass == Patch.FLAG_FOOTER) and (top > frameHeight / 2))
            

def _classify_navigation_fallback(frames):
    """Classify header and footer patches just by vertical position."""

    #         for r in self._renderers:
    #             r.resetItems()

    # if classifier 
    
    for frame in frames:
        frame_size = frame.sizeF()

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

            
def save_classifier(basename):
    filename = basename + '.pkl.bz2'
    return bz2_pickle.pickle(
        filename, (classifier, navigation_examples))


def load_classifier(basename):
    global classifier, navigation_examples
    filename = basename + '.pkl.bz2'
    if os.path.exists(filename):
        try:
            classifier, navigation_examples = bz2_pickle.unpickle(filename)
        except (ImportError, TypeError), e:
            sys.stderr.write("%s\n" % e)
