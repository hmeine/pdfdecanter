#  Copyright 2014-2014 Hans Meine <hans_meine@gmx.net>
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

import collections
from dynqt import QtCore, QtGui, getprop as p
import presentation

UNSEEN_OPACITY = 0.5
FADE_DURATION = 150
SLIDE_DURATION = 250

def _frameBoundingRect(item):
    result = QtCore.QRectF(item.boundingRect())
    pos = item.pos
    # in PythonQt, depending on whether the item is a QGraphicsWidget
    # or just a QGraphicsItem, pos may be a property (must not call)
    # or a method (needs call):
    if not isinstance(pos, QtCore.QPointF):
        pos = pos()
    result.translate(pos)
    return result

class FrameRenderer(QtGui.QGraphicsWidget):
    """QGraphicsWidget that renders a Frame instance.

    The FrameRenderer itself is a QGraphicsWidget in order to
    facilitate animations (geometry property etc.); it uses additional
    child graphics items for rendering the Frame:

    * one QGraphicsRectItem with the Frame.backgroundColor()
    * one QGraphicsPixmapItem per Patch
    * one QGraphicsProxyWidget per .mng link (movie player)
    * one QGraphicsRectItem for implementing the 'covered' state
    * custom items
    * optionally, QGraphicsRectItems for debugging link rects"""

    BACKGROUND_LAYER = -1
    # CONTENT_LAYER = 0
    # HEADER_LAYER = 1
    # FOOTER_LAYER = 2
    
    DEBUG = False # True

    # dictionary indexed by QGraphicsScene, containing
    # dictionary indexed by Frame instances, containing
    # lists of custom items for that frame in that scene
    _customItems = collections.defaultdict(lambda: collections.defaultdict(list))
    # dictionary indexed by custom items, containing
    # parents for resetting states after animations
    _originalCustomItemState = {}

    def __init__(self, parentItem):
        QtGui.QGraphicsWidget.__init__(self, parentItem)

        self._frame = None
        self._linkHandler = None
        self._helperItems = {}
        self._items = {}
        # possible keys:
        # - Patch instances
        # - links (as string)
        # - 'DEBUG_[somelink]' (link rects in debug mode)
        # - 'bg_<red>_<green>_<blue>'
        # - QGraphicsViewItems (custom content, key == value b/c source unknown)

        self._animation = None
        self._staticParents = {}

    def setLinkHandler(self, linkHandler):
        self._linkHandler = linkHandler

    @classmethod
    def addCustomFrameContent(cls, items, frame):
        """Add given custom items for the given frame."""

        if not items:
            return

        scene = items[0].scene()

        customItems = cls._customItems[scene]

        # add items:
        customItems[frame].extend(items)

        for item in items:
            cls._originalCustomItemState[item] = item.parentItem()

    def _frameItems(self, frame):
        class ResultItems(object):
            def __init__(self, items):
                self._existingItems = items
                self._newItems = {}
                self._key = None
            
            def get_existing_item(self, key):
                self._key = key
                layer, item = self._existingItems.get(key, (None, None))
                return item

            def add(self, item, layer, key = None):
                if key is None:
                    key = self._key
                    assert key is not None
                else:
                    assert self._key is None
                self._newItems[key] = (layer, item)
                self._key = None

            def __delitem__(self, index):
                del self._newItems[index]
                
            def items(self):
                return self._newItems.items()

            def added(self):
                return self._newItems
        
        result = ResultItems(self._items)

        debugRects = []

        for patch in frame.content():
            item = result.get_existing_item(key = patch)
            if item is None:
                if patch.flag(presentation.Patch.FLAG_RECT):
                    item = QtGui.QGraphicsRectItem()
                    item.setRect(patch.boundingRect())
                    item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                    item.setBrush(patch.color())
                    item.setPen(QtGui.QPen(QtCore.Qt.NoPen))
                else:
                    item = QtGui.QGraphicsPixmapItem()
                    item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                    item.setPos(QtCore.QPointF(patch.pos()))
                    item.setPixmap(patch.pixmap())
                    item.setTransformationMode(QtCore.Qt.SmoothTransformation)
            if patch.flag(presentation.Patch.FLAG_HEADER):
                layer = 'header'
            elif patch.flag(presentation.Patch.FLAG_FOOTER):
                layer = 'footer'
            elif patch.flag(presentation.Patch.FLAG_RECT):
                layer = 'bg'
            else:
                layer = 'content'
            result.add(item, layer)

            debugRects.append(('DEBUG_%s' % patch, _frameBoundingRect(item), layer))

        for rect, link in frame.linkRects():
            if link.startswith('file:') and link.endswith('.mng'):
                item = result.get_existing_item(key = link)
                if item is None:
                    if rect.width() < 1 and rect.height() < 1:
                        # bug in XeLaTeX w.r.t. images used in hyperlinks?
                        for patch in frame.patchesAt(QtCore.QPoint(rect.left() + 4, rect.top() - 4)):
                            rect = rect.united(QtCore.QRectF(patch.boundingRect()))

                    movie = QtGui.QMovie(link[5:])
                    player = QtGui.QLabel()
                    player.setMovie(movie)
                    movie.setScaledSize(rect.size().toSize())
                    player.resize(round(rect.width()), round(rect.height()))

                    item = QtGui.QGraphicsProxyWidget()
                    item.setWidget(player)
                    item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                    item.setPos(rect.topLeft())
                    movie.start()
                result.add(item, layer = 'content')

        staticItems = result.items()

        customItems = self._customItems[self._contentItem().scene()]
        for item in customItems[frame]:
            # add 1px border for partial volume effects:
            coveredRect = _frameBoundingRect(item).adjusted(-1, -1, 1, 1)

            for okey, (olayer, staticItem) in staticItems:
                # remove static content covered by custom content:
                if olayer == 'content' and coveredRect.contains(_frameBoundingRect(staticItem)):
                    # print "%s covers %s, del'ing %s -> %s..." % (
                    #     _frameBoundingRect(item), _frameBoundingRect(staticItem), key, staticItem)
                    del result[okey]

            item.show()
            result.add(item, layer = 'content', key = item)

            debugRects.append(('DEBUG_%s' % item, _frameBoundingRect(item), layer))

        if self.DEBUG:
            for rect, link in frame.linkRects(onlyExternal = False):
                debugRects.append(('DEBUG_%s' % link, rect, QtCore.Qt.yellow))

            for key, rect, layer in debugRects:
                item = result.get_existing_item(key)
                if item is None:
                    color = (QtCore.Qt.magenta
                             if layer == 'content' else
                             QtCore.Qt.green)
                    item = QtGui.QGraphicsRectItem(rect)
                    item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                    item.setPen(QtGui.QPen(color))
                result.add(item, layer)

        return result.added()

    def frame(self):
        return self._frame

    def _changeFrame(self, frame):
        """Internal helper for setFrame() / animatedTransition();
        change self._frame and returns the differences between the
        current items and the new ones as (newGeometry, addItems,
        removeItems) tuple."""
        
        self._resetAnimation()
        self._frame = frame
        newGeometry = QtCore.QRectF(p(self.pos), frame.sizeF())

        addItems = {}
        removeItems = dict(self._items)

        for key, (layer, item) in self._frameItems(frame).iteritems():
            try:
                del removeItems[key]
            except KeyError:
                parentItem = self._contentItem(layer)
                item.setParentItem(parentItem)
                addItems[key] = (layer, item)

        return newGeometry, addItems, removeItems

    def resetItems(self):
        """Re-setup items for the current frame.  Mostly makes sense
        if the DEBUG flag was toggled.  Similar to
        setFrame(self.frame()), but that would be a no-op."""
        
        self._setFrame(self._frame)
    
    def setFrame(self, frame):
        """Set rendered frame() to the given frame.  Immediately set
        up child items for the given frame."""
        
        if self._frame is not frame:
            self._setFrame(frame)

    def _setFrame(self, frame):
        newGeometry, addItems, removeItems = self._changeFrame(frame)

        self.setGeometry(newGeometry)
        self._items.update(addItems)
        self._removeItems(removeItems)

    def _removeItems(self, items):
        for key, (layer, item) in items.iteritems():
            # we must not remove custom items from the scene:
            if key is item:
                item.hide() # just hide them
            else:
                self.scene().removeItem(item)
            del self._items[key]

    def animatedTransition(self, sourceFrame, targetFrame):
        """Set up child items for an animated transition from
        sourceFrame to targetFrame.  Set rendered frame() to the
        targetFrame.  Return animation (QAnimation instance)."""
        
        self.setFrame(sourceFrame)
        if targetFrame is sourceFrame:
            return None # raise?

        # sliding transition (left/right) if Slide changes:
        slide = cmp(targetFrame.slide().slideIndex(),
                    sourceFrame.slide().slideIndex())

        oldGeometry = QtCore.QRectF(p(self.pos), self._frame.sizeF())
        newGeometry, addItems, removeItems = self._changeFrame(targetFrame)
        if oldGeometry != newGeometry:
            self._geometryAnimation = QtCore.QPropertyAnimation(self, 'geometry', self)
            self._geometryAnimation.setEndValue(newGeometry)
            self._geometryAnimation.setDuration(100)

        self._animation = QtCore.QParallelAnimationGroup()
        self._animation.finished.connect(self._resetAnimation)

        fadeOut = {}
        fadeIn = {}
        slideOut = {}
        slideIn = {}

        # decide which items to slide and which to fade out/in:
        if not slide:
            # within-Slide animation, no sliding here:
            fadeOut = dict(removeItems)
            fadeIn = addItems
        else:
            for oldKey, (oldLayer, oldItem) in removeItems.iteritems():
                # always slide custom items:
                if oldKey is oldItem:
                    slideOut[oldKey] = (oldLayer, oldItem)
                    continue

                # always fade non-Patches (e.g. backgrounds, movies, ...)
                if not isinstance(oldKey, presentation.Patch):
                    fadeOut[oldKey] = (oldLayer, oldItem)
                    continue

                # always fade header & footer:
                if (isinstance(oldKey, presentation.Patch) and
                    oldKey.flag(presentation.Patch.FLAG_HEADER | presentation.Patch.FLAG_FOOTER)):
                    fadeOut[oldKey] = (oldLayer, oldItem)
                    continue

                slideOut[oldKey] = (oldLayer, oldItem)

            for newKey, (newLayer, newItem) in addItems.iteritems():
                # always slide custom items:
                if newKey is newItem:
                    slideIn[newKey] = (newLayer, newItem)
                    continue

                # always fade non-Patches (e.g. backgrounds, movies, ...)
                if not isinstance(newKey, presentation.Patch):
                    fadeIn[newKey] = (newLayer, newItem)
                    continue

                # always fade header & footer:
                if (isinstance(newKey, presentation.Patch) and
                    newKey.flag(presentation.Patch.FLAG_HEADER | presentation.Patch.FLAG_FOOTER)):
                    fadeIn[newKey] = (newLayer, newItem)
                    continue

                # look for pairs (oldItem, newItem) of Patches where
                # newKey.isSuccessorOf(oldKey) => fade out/in
                changed = False
                for oldKey, (oldLayer, oldItem) in removeItems.iteritems():
                    if not isinstance(oldKey, presentation.Patch):
                        continue
                    if newKey.isSuccessorOf(oldKey):
                        changed = True
                        fadeOut[oldKey] = (oldLayer, oldItem)
                        fadeIn[newKey] = (newLayer, newItem)
                        del slideOut[oldKey]
                        break
                if not changed:
                    slideIn[newKey] = (newLayer, newItem)

        # don't fade out items that are completely covered by items that fade in:
        for newKey, (newLayer, newItem) in fadeIn.iteritems():
            coveredRect = _frameBoundingRect(newItem)
            for oldKey, (oldLayer, oldItem) in fadeOut.items():
                if coveredRect.contains(_frameBoundingRect(oldItem)):
                    del fadeOut[oldKey]

        offset = self._frame.sizeF().width() * slide

        # set up property animations for sliding/fading in/out:
        for items, contentName, duration, propName, startValue, endValue in (
                (slideOut, 'slideOut', SLIDE_DURATION,
                 'pos', QtCore.QPoint(0, 0), QtCore.QPoint(-offset, 0)),
                (slideIn, 'slideIn', SLIDE_DURATION,
                 'pos', QtCore.QPoint(offset, 0), QtCore.QPoint(0, 0)),
                (fadeOut, 'fadeOut', FADE_DURATION,
                 'opacity', 1.0, 0.0),
                (fadeIn, 'fadeIn', FADE_DURATION,
                 'opacity', 0.0, 1.0),
            ):
            if items:
                parentItems = set()

                for key, (layer, item) in items.iteritems():
                    parentItem = self._contentItem("%s-%s" % (layer, contentName))
                    self._staticParents[item] = item.parentItem()
                    item.setParentItem(parentItem)
                    parentItems.add(parentItem)

                for parentItem in parentItems:
                    anim = QtCore.QPropertyAnimation(parentItem, propName, self._animation)
                    anim.setDuration(duration)
                    anim.setStartValue(startValue)
                    anim.setEndValue(endValue)

        self._items.update(addItems)
        self._pendingRemove = removeItems

        self._animation.start()
        return self._animation

    def _resetAnimation(self):
        if not self._animation:
            return

        self._animation.stop()

        self._removeItems(self._pendingRemove)

        # reset parent of all animated contents:
        for i in range(self._animation.animationCount()):
            anim = self._animation.animationAt(i)
            for item in p(anim.targetObject).childItems():
                parentItem = self._staticParents[item]
                # custom items are special, because they're just
                # moved/reparented/hidden, but not created on the fly:
                origParent = self._originalCustomItemState.get(item)
                if origParent:
                    item.setParentItem(origParent)
                else:
                    item.setParentItem(parentItem)

        self._animation = None
        self._staticParents = {}

    def _frameRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._frame.sizeF())

    def headerItems(self):
        return [item for key, (layer, item) in self._items.iteritems()
                if isinstance(key, presentation.Patch) and key.flag(presentation.Patch.FLAG_HEADER)]

    def footerItems(self):
        return [item for key, (layer, item) in self._items.iteritems()
                if isinstance(key, presentation.Patch) and key.flag(presentation.Patch.FLAG_FOOTER)]

    def patchOf(self, item):
        """Return corresponding Patch instance which is rendered by
        the given item.  Return None if the item does not represent a
        Patch, or if the item does not belong to this renderer."""
        for key, (layer, thisItem) in self._items.iteritems():
            if thisItem is item:
                if isinstance(key, presentation.Patch):
                    return key
                else:
                    return None
        return None
    
    def _contentItem(self, key = 'content'):
        """QGraphicsWidget container child, used for animations"""
        result = self._helperItems.get(key, None)

        if result is None:
            result = QtGui.QGraphicsWidget(self)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            if isinstance(key, str) and key.startswith('bg'):
                result.setZValue(self.BACKGROUND_LAYER)
            self._helperItems[key] = result

        return result

    def mousePressEvent(self, event):
        if self._linkHandler:
            link = self._frame.linkAt(event.pos())
            if link is not None:
                if self._linkHandler(link):
                    event.accept()
                    return
        QtGui.QGraphicsWidget.mousePressEvent(self, event)


class SlideRenderer(FrameRenderer):    
    def __init__(self, slide, parentItem):
        FrameRenderer.__init__(self, parentItem)

        self._slide = slide
        # for preventing GC destroying custom items (PythonQt):
        self._customReferences = {}
        self._frameCallbacks = []

        assert len(slide) > 0
        self.showFrame(0)
        self._coverItem()

    def slide(self):
        return self._slide

    def _coverItem(self):
        result = self._helperItems.get('cover')
        
        if result is None:
            result = QtGui.QGraphicsRectItem(self._frameRect(), self)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            result.setBrush(QtCore.Qt.black)
            result.setOpacity(1.0 - UNSEEN_OPACITY)
            result.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            result.setZValue(1000)
            self._helperItems['cover'] = result

        result.setVisible(not self._slide.seen())
        return result

    def addCustomContent(self, items, subIndex, references = None):
        """Add given custom items to the SlideRenderer, for the given
        frame subIndex.  Optionally, pass references for preventing stuff to be garbage-collected
        (necessary for PythonQt)."""

        if not items:
            return

        parentItem = self._contentItem()
        for item in items:
            item.setParentItem(parentItem)

        self.addCustomFrameContent(items, self._slide[subIndex])

        if references:
            self._customReferences.update(references)

        # adjust visibility of custom items:
        customItems = self._customContent()
        for item in items:
            item.setVisible(item in customItems)

    def _customContent(self):
        return self._customItems[self.scene()][self._frame]

    def showCustomContent(self):
        for item in self._customContent():
            item.show()

    def addCustomCallback(self, cb):
        """Register callback for frame changes.  Expects callable that
        will be called with two arguments: the SlideRenderer (which
        can be queried for the currentSubIndex()) and the new frameIndex
        that is about to become the currentSubIndex().

        TODO: Call with None if slide becomes invisible/inactive."""
        self._frameCallbacks.append(cb)
        if self._slide.currentSubIndex() is not None:
            cb(self, self._slide.currentSubIndex())

    def uncover(self, seen = True):
        """Show slide with full opacity.  (Technically, hides dark,
        half-transparent cover item.)"""
        self._slide.setSeen(seen)
        self._coverItem().setVisible(not seen)

    def uncoverAll(self):
        """Like uncover(), but also shows all slide content.
        Equivalent to uncover(), followed by
        showFrame(lastSubFrameIndex)."""
        self.uncover()
        self.showFrame(len(self.slide())-1)

    def showFrame(self, subIndex, animateFrom = None):
        self._slide.setCurrentSubIndex(subIndex)

        if animateFrom is None:
            self.setFrame(self._slide.currentFrame())
        else:
            self.animatedTransition(animateFrom, self._slide.currentFrame())

        for cb in self._frameCallbacks:
            cb(self, subIndex)

def toggleDebug():
    global FADE_DURATION, SLIDE_DURATION
    
    FrameRenderer.DEBUG = not FrameRenderer.DEBUG

    factor = 4
    if FrameRenderer.DEBUG:
        FADE_DURATION *= factor
        SLIDE_DURATION *= factor
    else:
        FADE_DURATION /= factor
        SLIDE_DURATION /= factor
