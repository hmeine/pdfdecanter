from dynqt import QtCore, QtGui

UNSEEN_OPACITY = 0.5
BLEND_DURATION = 150


class FrameRenderer(QtGui.QGraphicsWidget):
    """QGraphicsWidget that renders a Frame instance.

    The FrameRenderer itself is a QGraphicsWidget in order to
    facilitate animations (geometry property etc.); it uses additional
    child graphics items for rendering the Frame:

    * one QGraphicsRectItem with the Frame.backgroundColor()
    * one QGraphicsPixmapItem per Patch
    * one QGraphicsProxyWidget per .mng link (movie player)
    * one QGraphicsRectItem for implementing the 'covered' state
    * custom items (TODO)
    * optionally, QGraphicsRectItems for debugging link rects"""
    
    DEBUG = False # True

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
        # - 'custom' (LIST of items!)

    def setLinkHandler(self, linkHandler):
        self._linkHandler = linkHandler

    def _frameItems(self, frame):
        result = {}

        color = frame.backgroundColor() if not self.DEBUG else QtCore.Qt.red
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

        return result

    def frame(self):
        return self._frame

    def _changeFrame(self, frame):
        """Internal helper for setFrame() / animatedTransition();
        change self._frame and returns the differences between the
        current items and the new ones as (newGeometry, addItems,
        removeItems) tuple."""

        self._frame = frame
        newGeometry = QtCore.QRectF(self.pos(), frame.size())

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
        for key, item in removeItems.iteritems():
            del self._items[key]

    def _frameRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._frame.size())

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
        self._frameCallbacks = []

        self.showFrame()
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

    def addCustomContent(self, items, frameIndex = 0):
        """Add given custom items to the SlideRenderer, for the given
        frameIndex.  If frameIndex is larger than the currently
        largest valid index, new frames will be added accordingly.  If
        frameIndex is None, it defaults to len(slide()),
        i.e. appending one new frame."""

        assert False, "FIXME: not implemented (add CustomItem to Frame contents, alongside Patches?)"

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
        parent.setVisible(frameIndex <= self._slide.currentSubIndex())
        for item in items:
            item.setParentItem(parent)

    def customItems(self):
        return self._items.get('custom', [])

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
        self._slide.setSeen(seen)
        self._coverItem().setVisible(not seen)

    def showFrame(self, frameIndex = 0):
        self._slide.setCurrentSubIndex(frameIndex)

        self.setFrame(self._slide.currentFrame())

        for cb in self._frameCallbacks:
            cb(self, frameIndex)

        return self
