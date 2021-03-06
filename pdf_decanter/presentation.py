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

import numpy, itertools
from .dynqt import QtCore, QtGui, qimage2ndarray
from . import pdf_infos


def boundingRect(rects):
    result = QtCore.QRect()
    for r in rects:
        result |= r
    return result


class ObjectWithFlags(object):
    """Mix-In class for objects that support bit flags."""

    __slots__ = ('_flags', )

    def __init__(self):
        super(ObjectWithFlags, self).__init__()
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


class Patch(ObjectWithFlags):
    """Positioned image representing a visual patch of a presentation.
    If FLAG_RECT is set, this is a patch of color() without image
    data; image() then contains the size (QSizeF) of the patch (and
    pos() will be a QPointF instead of an integer QPoint).
    May appear on multiple frames / slides."""
    
    __slots__ = ('_pos', '_image', '_pixmap', '_occurrenceCount', '_color')

    FLAG_HEADER     = 1
    FLAG_FOOTER     = 2
    MASK_NAVIGATION = (FLAG_HEADER | FLAG_FOOTER)
    FLAG_RECT       = 4
    FLAG_MONOCHROME = 8
    MASK_TYPE       = (FLAG_RECT | FLAG_MONOCHROME)

    def __init__(self, pos, image, occurrenceCount, color = None):
        super(Patch, self).__init__()
        self._pos = pos
        self._image = image
        self._pixmap = None
        self._occurrenceCount = occurrenceCount
        self._color = color

    def pos(self):
        return self._pos

    def boundingRect(self):
        if self.flag(self.FLAG_RECT):
            return QtCore.QRectF(self._pos, self._image)
        return QtCore.QRect(self._pos, self._image.size())

    def xy(self):
        return self._pos.x(), self._pos.y()

    def sizePair(self):
        return (self._image.width(), self._image.height())

    def ndarray(self):
        assert not self.flag(self.FLAG_RECT)
        if self.flag(self.FLAG_MONOCHROME):
            return qimage2ndarray.alpha_view(self._image)
        return qimage2ndarray.raw_view(self._image)

    def pixmap(self):
        assert not self.flag(self.FLAG_RECT)
        if self._pixmap is None:
            self._pixmap = QtGui.QPixmap.fromImage(self._image)
        return self._pixmap

    def pixelCount(self):
        """Return number of pixels as some kind of measurement of memory usage."""
        if self.flag(self.FLAG_RECT):
            return 0
        result = self._image.width() * self._image.height()
        if self.flag(self.FLAG_MONOCHROME):
            result /= 4
        return result

    def occurrenceCount(self):
        return self._occurrenceCount

    def isSuccessorOf(self, other):
        return self.boundingRect() == other.boundingRect()

    def __iter__(self):
        yield self._pos
        yield self._image

    def color(self):
        return self._color

    def __getstate__(self):
        return (self.xy(), self.ndarray().copy()
                if not self.flag(self.FLAG_RECT) else self.sizePair(),
                self._flags, self.occurrenceCount(),
                self._color and self._color.rgb())

    def __setstate__(self, state):
        (x, y), patch, self._flags, self._occurrenceCount, color = state
        if self.flag(self.FLAG_RECT):
            self._pos = QtCore.QPointF(x, y) # (float pos)
            w, h = patch
            self._image = QtCore.QSizeF(w, h)
        else:
            self._pos = QtCore.QPoint(x, y) # (integer pos)
            h, w = patch.shape
            self._image = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
            if self.flag(self.FLAG_MONOCHROME):
                qimage2ndarray.raw_view(self._image)[:] = color
                qimage2ndarray.alpha_view(self._image)[:] = patch
            else:
                qimage2ndarray.raw_view(self._image)[:] = patch
        self._pixmap = None
        self._color = QtGui.QColor(color)

    def __repr__(self):
        flags = []
        for flag, desc in ((self.FLAG_HEADER,     'HEADER'),
                           (self.FLAG_FOOTER,     'FOOTER'),
                           (self.FLAG_RECT,       'RECT'),
                           (self.FLAG_MONOCHROME, 'MONOCHROME')):
            if self.flag(flag):
                flags.append(desc)
        if flags:
            flags = " (%s)" % ", ".join(flags)
        else:
            flags = ""
        return "<Patch at %s, %s, %sx%s%s>" % (
            self.xy() + self.sizePair() + (flags, ))


class Frame(object):
    """Single frame (PDF page) with content, header, footer.  Belongs
    to a parent Slide."""

    __slots__ = ('_size', '_content', '_slide', '_pdfPageInfos')

    def __init__(self, size, contentPatches, slide = None):
        self._size = size
        self._content = contentPatches
        self._slide = slide
        self._pdfPageInfos = None

    def __repr__(self):
        return "<Frame %s, size %sx%s, %d patches>" % (
            self.frameIndex() if self._slide is not None else 'at %0xd' % id(self),
            self.sizeF().width(), self.sizeF().height(), len(self.content()))

    def setSlide(self, slide):
        """Set parent slide; expected to be called by Slide.addFrame()."""
        self._slide = slide

    def slide(self):
        """Return slide this frame belongs to (one level up in the
        compositional hierarchy)."""
        return self._slide

    def header(self):
        """Return list of content patches with the FLAG_HEADER flag set"""
        return [patch for patch in self._content
                if patch.flag(Patch.FLAG_HEADER)]

    def footer(self):
        """Return list of content patches with the FLAG_FOOTER flag set"""
        return [patch for patch in self._content
                if patch.flag(Patch.FLAG_FOOTER)]

    def presentation(self):
        """Return presentation this frame belongs to (two levels up in
        the compositional hierarchy).  Equivalent to
        .slide().presentation()."""
        return self._slide.presentation()

    def sizeF(self):
        """Return size (in pixels, as QSizeF) of this Frame"""
        return QtCore.QSizeF(self._size)

    def content(self):
        return self._content

    def patchSet(self):
        return set(self._content)

    def patchesAt(self, pos):
        posF = QtCore.QPointF(pos)
        for patch in self._content:
            if patch.boundingRect().contains(pos if not patch.flag(Patch.FLAG_RECT) else posF):
                yield patch

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

        frameSize = self.sizeF()

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
        
        frameSize = self.sizeF()
        relPos = (pos.x() / frameSize.width(),
                  (frameSize.height() - pos.y()) / frameSize.height())
        for rect, link in self._pdfPageInfos.relativeLinks():
            if numpy.all((relPos >= rect[0]) * (relPos <= rect[1])):
                return link
        return None

    def isSuccessorOf(self, other):
        """Return whether this Frame is likely to be the 'successor'
        of the given other one.  This is assumed to be the case if
        only new ChangedRects appear, or disappearing ChangedRects
        have a corresponding successor
        (cf. ChangedRect.isSuccessorOf()).
        """
        if self.sizeF() != other.sizeF():
            return False

        if self.header() == other.header():
            return True
        
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

    def __getstate__(self):
        return ((self._size.width(), self._size.height()),
                self._content,
                self._slide)

    def __setstate__(self, state):
        (w, h), content, slide = state
        self._size = QtCore.QSizeF(w, h)
        self._content = content
        self._slide = slide
        self._pdfPageInfos = None


class Slide(object):
    """Collection of Frames that belong together, i.e. PDF pages that
    represent transition states of the same presentation slide.  It is
    assumed that all frames have the same size."""
    
    __slots__ = ('_presentation', '_frames', '_currentSubIndex', '_seen')
    
    def __init__(self, presentation):
        assert presentation is not None
        self._presentation = presentation
        self._frames = []

        self._currentSubIndex = None
        self._seen = False

    def sizeF(self):
        return self._frames[0].sizeF()

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
        result = QtCore.QRectF(QtCore.QPointF(0, 0), self.sizeF())

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
            assert frame.sizeF() == self.sizeF()
        
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

    def __delitem__(self, index):
        del self._frames[index]

    def __delslice__(self, start, end):
        del self._frames[start:end]

    def __getstate__(self):
        return (self._frames, )

    def __setstate__(self, state):
        frames, = state
        self._presentation = None
        self._frames = frames
        # __init__ is not called:
        self._currentSubIndex = None
        self._seen = None


class Presentation(list):
    """List of slides."""

    def __init__(self, infos = None):
        self._pdfInfos = infos
        self.structureChanged()

    def structureChanged(self):
        """Update internal structures after Slides or Frames have been
        added, removed, or reordered.  This function is not automatically called, but must be called for several functions to work, e.g. frameCount() or frame(idx)."""
        self._frame2Slide = []
        self._slide2Frame = []
        for i, s in enumerate(self):
            self._slide2Frame.append(len(self._frame2Slide))
            self._frame2Slide.extend([(i, j) for j in range(len(s))])
            s._presentation = self

    def pdfInfos(self):
        return self._pdfInfos

    def _beamerSubIndices(self):
        if self._pdfInfos:
            try:
                it = iter(pdf_infos.labeledBeamerFrames(self._pdfInfos))
                name, pages = next(it)
                for pageNumber in itertools.count():
                    if pageNumber > pages[-1]:
                        name, pages = next(it)
                    if pageNumber in pages:
                        yield pages.index(pageNumber)
                    else:
                        yield None
            except StopIteration:
                pass
        while True:
            yield None

    def addFrames(self, frames):
        prevFrame = None
        for frame, subIndex in zip(frames, self._beamerSubIndices()):
            # new Slide?
            if not prevFrame or subIndex == 0 or (
                    subIndex is None and not frame.isSuccessorOf(prevFrame)):
                self.append(Slide(self))

            self[-1].addFrame(frame)
            prevFrame = frame

        self.structureChanged()

        self.setPDFInfos(self._pdfInfos) # call Frame.setPDFPageInfos()

    def slideCount(self):
        return len(self)

    def frameCount(self):
        return len(self._frame2Slide)

    def frames(self):
        for slide in self:
            for frame in slide:
                yield frame

    def slide(self, slideIndex):
        if isinstance(slideIndex, str):
            if not self._pdfInfos:
                raise RuntimeError("accessing slides by name is not possible without PDFInfos")
            frameIndex = self._pdfInfos.names().get(slideIndex)
            if frameIndex is None:
                raise RuntimeError("no PDF anchor named %r found" % slideIndex)
            slideIndex, subIndex = self._frame2Slide[frameIndex]
        return self[slideIndex]

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
        self.structureChanged()
