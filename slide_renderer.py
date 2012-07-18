from dynqt import QtCore, QtGui

UNSEEN_OPACITY = 0.5

class SlideRenderer(QtGui.QGraphicsWidget):
    DEBUG = False # True

    def __init__(self, slide, parentItem):
        QtGui.QGraphicsWidget.__init__(self, parentItem)
        self._slide = slide
        self.setGeometry(QtCore.QRectF(QtCore.QPointF(0, 0), slide.size()))
        #self.setFlag(QtGui.QGraphicsItem.ItemIsMovable)
        self.setFlag(QtGui.QGraphicsItem.ItemIsSelectable)

        self._currentFrame = None
        self._seen = False
        self._frameCallbacks = []
        self._linkHandler = None

        self._items = {}

        self.showFrame()

    def slide(self):
        return self._slide

    def setLinkHandler(self, linkHandler):
        self._linkHandler = linkHandler

    def _setupItems(self):
        self._backgroundItem()

        contentItem = QtGui.QGraphicsWidget(self)
        contentItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self._items['content'] = contentItem

        navigationItem = QtGui.QGraphicsWidget(self)
        navigationItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self._items['navigation'] = navigationItem

        self.frameItem('header')
        self.frameItem('footer')

        self._coverItem()

    def _slideRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._slide.size())

    def _rectItem(self, color, key):
        result = self._items.get(key, None)
        
        if result is None:
            result = QtGui.QGraphicsRectItem(self._slideRect(), self)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            result.setBrush(color)
            result.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            self._items[key] = result

        return result

    def _backgroundItem(self):
        return self._rectItem(QtCore.Qt.white if not self.DEBUG else QtCore.Qt.red, key = 'bg')

    def _coverItem(self):
        result = self._rectItem(QtCore.Qt.black, key = 'cover')
        result.setZValue(1000)
        result.setOpacity(1.0 - UNSEEN_OPACITY)
        result.setVisible(not self._seen)
        return result

    def frameItem(self, frameIndex):
        result = self._items.get(frameIndex, None)
        
        if result is None:
            if frameIndex == 'header':
                patches = self._slide.header() or ()
                parentItem = self._items['navigation']
                zValue = 50
            elif frameIndex == 'footer':
                patches = self._slide.footer() or ()
                parentItem = self._items['navigation']
                zValue = 50
            else:
                patches = self._slide.frame(frameIndex)
                parentItem = self._items['content']
                zValue = 100 + frameIndex

            result = QtGui.QGraphicsWidget(parentItem)
            result.setZValue(zValue)
            result.setAcceptedMouseButtons(QtCore.Qt.NoButton)

            for pos, patch in patches:
                pixmap = QtGui.QPixmap.fromImage(patch)
                pmItem = QtGui.QGraphicsPixmapItem(result)
                pmItem.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                pmItem.setPos(QtCore.QPointF(pos))
                pmItem.setPixmap(pixmap)
                pmItem.setTransformationMode(QtCore.Qt.SmoothTransformation)

            if parentItem is self._items['content']:
                for rect, link in self._slide.linkRects(frameIndex):
                    if link.startswith('file:') and link.endswith('.mng'):
                        movie = QtGui.QMovie(link[5:])
                        player = QtGui.QLabel()
                        player.setMovie(movie)
                        movie.setScaledSize(rect.size().toSize())
                        player.resize(round(rect.width()), round(rect.height()))
                        item = QtGui.QGraphicsProxyWidget(result)
                        item.setWidget(player)
                        item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                        item.setPos(rect.topLeft())
                        movie.start()

                if self.DEBUG:
                    for rect, link in self._slide.linkRects(frameIndex, onlyExternal = False):
                        linkFrame = QtGui.QGraphicsRectItem(rect, parentItem)
                        linkFrame.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                        linkFrame.setPen(QtGui.QPen(QtCore.Qt.yellow))

            self._items[frameIndex] = result

        return result

    def mousePressEvent(self, event):
        if self._linkHandler:
            link = self._slide.linkAt(self._currentFrame, event.pos())
            if link is not None:
                self._linkHandler(link)
                event.accept()
                return
        QtGui.QGraphicsWidget.mousePressEvent(self, event)

    def navigationItem(self):
        return self._items['navigation']

    def contentItem(self):
        return self._items['content']

    def addCustomContent(self, items, frameIndex = 0):
        """Add given custom items to the SlideRenderer, for the given
        frameIndex.  If frameIndex is larger than the currently
        largest valid index, new frames will be added accordingly.  If
        frameIndex is None, it defaults to len(slide()),
        i.e. appending one new frame."""

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
        parent.setVisible(frameIndex <= self._currentFrame)
        for item in items:
            item.setParentItem(parent)

    def customItems(self):
        return self._items.get('custom', [])

    def addCustomCallback(self, cb):
        """Register callback for frame changes.  Expects callable that
        will be called with two arguments: the SlideRenderer (which
        can be queried for the currentFrame()) and the new frameIndex
        that is about to become the currentFrame().

        TODO: Call with None if slide becomes invisible/inactive."""
        self._frameCallbacks.append(cb)
        if self._currentFrame is not None:
            cb(self, self._currentFrame)

    def uncover(self, seen = True):
        self._seen = seen
        self._coverItem().setVisible(not seen)

    def showFrame(self, frameIndex = 0):
        if not self._items:
            self._setupItems()

        for cb in self._frameCallbacks:
            cb(self, frameIndex)

        self._currentFrame = frameIndex

        for i in range(0, self._currentFrame + 1):
            item = self.frameItem(i)
            item.setVisible(True)
            if self.DEBUG:
                item.setOpacity(0.5 if i < frameIndex else 1.0)

        for i in range(frameIndex + 1, len(self._slide)):
            if i in self._items:
                self._items[i].setVisible(False)

        return self

    def currentFrame(self):
        return self._currentFrame
