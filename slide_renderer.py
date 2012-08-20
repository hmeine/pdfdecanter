from dynqt import QtCore, QtGui

UNSEEN_OPACITY = 0.5


class FrameRenderer(QtGui.QGraphicsWidget):
    DEBUG = False # True

    def __init__(self, parentItem):
        QtGui.QGraphicsWidget.__init__(self, parentItem)

        self._frame = None
        self._linkHandler = None
        self._items = {}

    def setLinkHandler(self, linkHandler):
        self._linkHandler = linkHandler

    def _frameItems(self, frame):
        result = {}

        for patch in frame.content():
            pmItem = QtGui.QGraphicsPixmapItem()
            pmItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            pmItem.setPos(QtCore.QPointF(patch.pos()))
            pmItem.setPixmap(patch.pixmap())
            pmItem.setTransformationMode(QtCore.Qt.SmoothTransformation)
            result[patch] = pmItem

        for rect, link in frame.linkRects():
            if link.startswith('file:') and link.endswith('.mng'):
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
                linkFrame = QtGui.QGraphicsRectItem(rect)
                linkFrame.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                linkFrame.setPen(QtGui.QPen(QtCore.Qt.yellow))
                result['DEBUG_%s' % link] = linkFrame

        return result

    def setFrame(self, frame):
        if self._frame is frame:
            return

        self._frame = frame
        self.setGeometry(QtCore.QRectF(QtCore.QPointF(0, 0), frame.size()))

        parentItem = self.contentItem()
        items = self._frameItems(frame)
        for item in items.values():
            item.setParentItem(parentItem)
        self._items.update(items)

    def _frameRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._frame.size())

    def _rectItem(self, color, key):
        result = self._items.get(key, None)
        
        if result is None:
            result = QtGui.QGraphicsRectItem(self._frameRect(), self)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            result.setBrush(color)
            result.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            self._items[key] = result

        return result

    def _backgroundItem(self):
        return self._rectItem(self._frame.backgroundColor()
                              if not self.DEBUG else QtCore.Qt.red,
                              key = 'bg')

    def contentItem(self):
        result = self._items.get('content', None)

        if result is None:
            self._backgroundItem()

            result = QtGui.QGraphicsWidget(self)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            self._items['content'] = result

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

    def slide(self):
        return self._slide

    def _coverItem(self):
        result = self._rectItem(QtCore.Qt.black, key = 'cover')
        result.setZValue(1000)
        result.setOpacity(1.0 - UNSEEN_OPACITY)
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
