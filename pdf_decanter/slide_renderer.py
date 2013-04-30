import collections
from dynqt import QtCore, QtGui, getprop as p
import presentation

UNSEEN_OPACITY = 0.5
FADE_DURATION = 150
SLIDE_DURATION = 250

def _frameBoundingRect(item):
    result = QtCore.QRectF(item.boundingRect())
    pos = item.pos
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
        result = {}

        color = frame.backgroundColor() if not self.DEBUG else QtGui.QColor(230, 200, 200)
        key = 'bg_%d_%d_%d' % color.getRgb()[:3]
        bgItem = self._items.get(key, None)
        if bgItem is None:
            bgItem = QtGui.QGraphicsRectItem(self._frameRect(), self)
            bgItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            bgItem.setBrush(color)
            bgItem.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            bgItem.setZValue(-1)
        result[key] = bgItem

        for patch in frame.content():
            pmItem = self._items.get(patch, None)
            if pmItem is None:
                pmItem = QtGui.QGraphicsPixmapItem()
                pmItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                pmItem.setPos(QtCore.QPointF(patch.pos()))
                pmItem.setPixmap(patch.pixmap())
                pmItem.setTransformationMode(QtCore.Qt.SmoothTransformation)
            result[patch] = pmItem

            if self.DEBUG:
                key = 'DEBUG_%s' % patch
                borderItem = self._items.get(key, None)
                if borderItem is None:
                    borderItem = QtGui.QGraphicsRectItem(_frameBoundingRect(pmItem))
                    borderItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                    borderItem.setPen(QtGui.QPen(QtCore.Qt.magenta))
                result[key] = borderItem

        for rect, link in frame.linkRects():
            if link.startswith('file:') and link.endswith('.mng'):
                item = self._items.get(link, None)
                if item is None:
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
                result[link] = item

        if self.DEBUG:
            for rect, link in frame.linkRects(onlyExternal = False):
                key = 'DEBUG_%s' % link
                linkFrame = self._items.get(key, None)
                if linkFrame is None:
                    linkFrame = QtGui.QGraphicsRectItem(rect)
                    linkFrame.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                    linkFrame.setPen(QtGui.QPen(QtCore.Qt.yellow))
                result[key] = linkFrame

        staticItems = result.items()

        customItems = self._customItems[self._contentItem().scene()]
        for item in customItems[frame]:
            # add 1px border for partial volume effects:
            coveredRect = _frameBoundingRect(item).adjusted(-1, -1, 1, 1)

            for key, staticItem in staticItems:
                # remove items covered by custom content:
                if coveredRect.contains(_frameBoundingRect(staticItem)):
                    # print "%s covers %s, del'ing %s -> %s..." % (
                    #     _frameBoundingRect(item), _frameBoundingRect(staticItem), key, staticItem)
                    del result[key]
            result[item] = item
            item.show()

            if self.DEBUG:
                key = 'DEBUG_%s' % patch
                borderItem = self._items.get(key, None)
                if borderItem is None:
                    borderItem = QtGui.QGraphicsRectItem(_frameBoundingRect(item))
                    borderItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                    borderItem.setPen(QtGui.QPen(QtCore.Qt.cyan))
                result[key] = borderItem

        return result

    def frame(self):
        return self._frame

    def _changeFrame(self, frame):
        """Internal helper for setFrame() / animatedTransition();
        change self._frame and returns the differences between the
        current items and the new ones as (newGeometry, addItems,
        removeItems) tuple."""

        self._resetAnimation()
        self._frame = frame
        newGeometry = QtCore.QRectF(p(self.pos), frame.size())

        parentItem = self._contentItem()

        addItems = {}
        removeItems = dict(self._items)
        
        items = self._frameItems(frame)
        for key, item in items.iteritems():
            try:
                del removeItems[key]
            except KeyError:
                item.setParentItem(parentItem)
                addItems[key] = item
        
        return newGeometry, addItems, removeItems

    def setFrame(self, frame):
        if self._frame is frame:
            return

        newGeometry, addItems, removeItems = self._changeFrame(frame)

        self.setGeometry(newGeometry)
        self._items.update(addItems)
        self._removeItems(removeItems)

    def _removeItems(self, items):
        for key, item in items.iteritems():
            # we must not remove custom items from the scene:
            if key is item:
                item.hide() # just hide them
            else:
                self.scene().removeItem(item)
            del self._items[key]

    def animatedTransition(self, sourceFrame, targetFrame):
        self.setFrame(sourceFrame)
        if targetFrame is sourceFrame:
            return # raise?

        # sliding transition (left/right) if Slide changes:
        slide = cmp(targetFrame.slide().slideIndex(),
                    sourceFrame.slide().slideIndex())

        oldGeometry = QtCore.QRectF(p(self.pos), self._frame.size())
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
            for oldKey, oldItem in removeItems.iteritems():
                # always fade header & footer:
                if (isinstance(oldKey, presentation.Patch) and
                    oldKey.flag(presentation.Patch.FLAG_HEADER | presentation.Patch.FLAG_FOOTER)):
                    fadeOut[oldKey] = oldItem
                else:
                    slideOut[oldKey] = oldItem

            for newKey, newItem in addItems.iteritems():
                # always slide custom items:
                if newKey is newItem:
                    slideIn[newKey] = newItem
                    continue

                # always fade non-Patches (e.g. backgrounds, movies, ...)
                if not isinstance(newKey, presentation.Patch):
                    fadeIn[newKey] = newItem
                    continue

                # always fade header & footer:
                if (isinstance(newKey, presentation.Patch) and
                    newKey.flag(presentation.Patch.FLAG_HEADER | presentation.Patch.FLAG_FOOTER)):
                    fadeIn[newKey] = newItem
                    continue

                # look for pairs (oldItem, newItem) of Patches where
                # newKey.isSuccessorOf(oldKey) => fade out/in
                changed = False
                for oldKey, oldItem in removeItems.iteritems():
                    if not isinstance(oldKey, presentation.Patch):
                        continue
                    if newKey.isSuccessorOf(oldKey):
                        changed = True
                        fadeOut[oldKey] = oldItem
                        fadeIn[newKey] = newItem
                        del slideOut[oldKey]
                        break
                if not changed:
                    slideIn[newKey] = newItem

        # don't fade out items that are completely covered by items that fade in:
        for newKey, newItem in fadeIn.iteritems():
            coveredRect = _frameBoundingRect(newItem)
            for oldKey, oldItem in fadeOut.items():
                if coveredRect.contains(_frameBoundingRect(oldItem)):
                    del fadeOut[oldKey]

        offset = self._frame.size().width() * slide

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
                parentItem = self._contentItem(contentName)
                for key, item in items.iteritems():
                    item.setParentItem(parentItem)

                anim = QtCore.QPropertyAnimation(parentItem, propName, self._animation)
                anim.setDuration(duration)
                anim.setStartValue(startValue)
                anim.setEndValue(endValue)

        self._items.update(addItems)
        self._pendingRemove = removeItems

        self._animation.start()

    def _resetAnimation(self):
        if not self._animation:
            return

        self._animation.stop()

        # reset parent of all animated contents:
        parentItem = self._contentItem()
        for i in range(self._animation.animationCount()):
            anim = self._animation.animationAt(i)
            for item in p(anim.targetObject).childItems():
                item.setParentItem(parentItem)
                # custom items are special, because they're just
                # moved/reparented/hidden, but not created on the fly:
                origParent = self._originalCustomItemState.get(item)
                if origParent:
                    item.setParentItem(origParent)

        self._removeItems(self._pendingRemove)

        self._animation = None

    def _frameRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._frame.size())

    def headerItems(self):
        return [item for key, item in self._items.iteritems()
                if isinstance(key, presentation.Patch) and key.flag(presentation.Patch.FLAG_HEADER)]

    def footerItems(self):
        return [item for key, item in self._items.iteritems()
                if isinstance(key, presentation.Patch) and key.flag(presentation.Patch.FLAG_FOOTER)]

    def _contentItem(self, key = 'content'):
        """QGraphicsWidget container child, used for animations"""
        result = self._helperItems.get(key, None)

        if result is None:
            result = QtGui.QGraphicsWidget(self)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)
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
