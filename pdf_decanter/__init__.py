from __future__ import division

from dynqt import QtCore, QtGui, QtOpenGL, getprop as p

import numpy, os, sys, time, math, operator
import pdftoppm_renderer, pdf_infos, bz2_pickle
import presentation, slide_renderer

try:
    import poppler_renderer
except ImportError, e:
    print 'QtPoppler not found, falling back to pdftoppm...'
    renderer = pdftoppm_renderer
else:
    renderer = poppler_renderer

__version__ = "0.1"


PADDING_X = 0.03 # 3% of frame width
PADDING_Y = 0.03 # 3% of frame height
LINEBREAK_PADDING = 2.5 * PADDING_Y
INDENT_X = 0 # 0.125


class GeometryAnimation(QtCore.QVariantAnimation):
    def __init__(self, item, parent = None):
        QtCore.QVariantAnimation.__init__(self, parent)
        self._item = item

    def updateCurrentValue(self, value):
        self._item.setPos(value.topLeft())
        self._item.setScale(value.width())


class PDFDecanter(QtCore.QObject):
    """Main presentation program using the QGraphicsView framework for
    rendering.

    It is supported to use an existing view for the presentation, so
    this class does not directly represent a window (or widget).
    Instead, eventFilter() is used to catch events for the view (and
    scene), and pass them on to methods like resizeEvent(), simulating
    the usual methods of a regular QWidget.

    The QGraphicsScene is set to the window size (and this relation is
    maintained in resizeEvent).  The root item in the scene is a
    QGraphicsWidget (_presentationItem) that indirectly contains a
    grid (cf. _setupGrid) of SlideRenderer items (_renderers) with a
    layout used for the overview mode.  The _presentationItem is used
    for zooming out into the overview mode and back.  Between the
    _presentationItem and the renderers, there is a viewport
    (cf. _slideViewport) that serves as a clipping rect, in order to
    hide neighboring slides in case of a larger window (e.g. 16:9
    fullscreen with 4:3 slides)."""
    
    def __init__(self, view = None):
        QtCore.QObject.__init__(self)

        if view is None:
            view = QtGui.QGraphicsView()
            w, h = self.slideSize()
            view.resize(w, h)
        self._view = view

        self._view.installEventFilter(self)

        self._view.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

        self._view.setFrameStyle(QtGui.QFrame.NoFrame)
        self._view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        if view.scene() is not None:
            self._scene = view.scene()
            self._scene.setSceneRect(0, 0, p(self._view.width), p(self._view.height))
        else:
            self._scene = QtGui.QGraphicsScene(0, 0, p(self._view.width), p(self._view.height))
            self._view.setScene(self._scene)
        self._scene.setBackgroundBrush(QtCore.Qt.black)
        self._scene.installEventFilter(self) # for MouseButtonRelease events

        self._presentationItem = QtGui.QGraphicsWidget()
        self._scene.addItem(self._presentationItem)

        self._slideViewport = QtGui.QGraphicsRectItem(self._presentationItem)
        self._slideViewport.setFlag(QtGui.QGraphicsItem.ItemClipsChildrenToShape)

        self._cursor = None

        self._renderers = None
        self._currentFrameIndex = None

        self._gotoSlideIndex = None
        self._gotoSlideTimer = QtCore.QTimer(self)
        self._gotoSlideTimer.setSingleShot(True)
        self._gotoSlideTimer.setInterval(1000)
        self._gotoSlideTimer.timeout.connect(self._clearGotoSlide)

        self._hideMouseTimer = QtCore.QTimer(self)
        self._hideMouseTimer.setSingleShot(True)
        self._hideMouseTimer.setInterval(1000)
        self._hideMouseTimer.timeout.connect(self._hideMouse)
        self._hideMouseTimer.start()

        self._view.viewport().setMouseTracking(True)
        self._view.viewport().installEventFilter(self)

        self._inOverview = False

    def enableGL(self):
        try:
            from OpenGL import GL
        except ImportError:
            sys.stderr.write("WARNING: OpenGL could not be imported, running without GL...\n")
            return False

        glWidget = QtOpenGL.QGLWidget(QtOpenGL.QGLFormat(QtOpenGL.QGL.SampleBuffers))
        if not glWidget.isValid():
            sys.stderr.write("WARNING: Could not create valid OpenGL context, running without GL...\n")
            return False

        self._view.setViewport(glWidget)
        self._view.setViewportUpdateMode(QtGui.QGraphicsView.FullViewportUpdate)
        self._view.viewport().setMouseTracking(True)
        self._view.viewport().installEventFilter(self)
        return True

    def view(self):
        return self._view

    def slideSize(self):
        """Return size at which to render PDFs"""
        return 1024, 768 # TODO: make this an option

    def presentationBounds(self):
        result = QtCore.QRectF()
        for renderer in self._renderers:
            br = renderer.boundingRect()
            br.translate(p(renderer.pos))
            result |= br
        return result

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseMove:
            self.mouseMoveEvent(event)
            return False

        event.ignore()
        if obj is self._view:
            if event.type() == QtCore.QEvent.KeyPress:
                self.keyPressEvent(event)
            elif event.type() == QtCore.QEvent.Resize:
                self.resizeEvent(event)
            elif event.type() == QtCore.QEvent.Wheel:
                self.wheelEvent(event)
        elif obj is self._scene:
            if event.type() == QtCore.QEvent.GraphicsSceneMousePress:
                self.mousePressEvent(event)
            elif event.type() == QtCore.QEvent.GraphicsSceneMouseRelease:
                self.mouseReleaseEvent(event)
        if event.isAccepted():
            return True
        return False

    def resizeEvent(self, e):
        assert p(self._view.size) == e.size()
        self._scene.setSceneRect(0, 0, p(self._view.width), p(self._view.height))
        self._adjustSlideViewport()
        pres = self._presentationItem
        if not self._inOverview:
            renderer = self._currentRenderer()
            if not renderer:
                return
            scale, margin = self._maxpectScaleAndMargin(renderer.frame().size())
            pres.setPos(QtCore.QPointF(margin.width(), margin.height()) - p(renderer.pos) * scale)
        else:
            scale = self._overviewScale()
        pres.setScale(scale)

    def _adjustSlideViewport(self):
        if self._currentFrameIndex is None:
            return

        if not self._inOverview:
            renderer = self._currentRenderer()
            viewportRect = QtCore.QRectF(p(renderer.pos), p(renderer.size))
        else:
            viewportRect = self.presentationBounds()

        self._slideViewport.setRect(viewportRect)

    def wheelEvent(self, e):
        if self._inOverview:
            overview = self._presentationItem
            overviewPos = p(overview.pos)
            overviewPos.setY(overviewPos.y() + e.delta())
            self._adjustOverviewPos(overviewPos, self._overviewScale())
            overview.setPos(overviewPos)
        else:
            e.ignore()

    def mouseMoveEvent(self, e):
        self._view.unsetCursor()
        self._hideMouseTimer.start()

    def _hideMouse(self):
        self._view.setCursor(QtCore.Qt.BlankCursor)

    def mousePressEvent(self, e):
        self._mousePressPos = e.screenPos()

    def mouseReleaseEvent(self, e):
        wasClick = (self._mousePressPos is not None) \
            and (e.screenPos() - self._mousePressPos).manhattanLength() < 6
        self._mousePressPos = None
        if not wasClick:
            return

        if not self._inOverview:
            # RMB: overview
            if e.button() == QtCore.Qt.RightButton:
                self.showOverview()
            # MMB: go back one frame (if not at beginning):
            elif e.button() == QtCore.Qt.MiddleButton:
                if self._currentFrameIndex > 0:
                    self.gotoFrame(self._currentFrameIndex - 1)
            # LMB: advance one frame (if not at end):
            else:
                if self._currentFrameIndex < self._slides.frameCount() - 1:
                    self.gotoFrame(self._currentFrameIndex + 1)
        else:
            # find frame clicked on in overview and jump to it:
            for item in self._scene.items(e.scenePos()):
                #if isinstance(item, slide_renderer.SlideRenderer):
                if item in self._renderers:
                    slideIndex = self._renderers.index(item)
                    self.gotoFrame(self._slides[slideIndex].currentFrame().frameIndex())
                    break

    def loadPDF(self, pdfFilename, cacheFilename = None, useCache = None, createCache = False):
        slides = None

        if cacheFilename is None:
            pdfFilename = os.path.abspath(pdfFilename)
            dirname, basename = os.path.split(pdfFilename)
            cacheFilename = os.path.join(
                dirname, "pdf_decanter_cache_%s.bz2" % os.path.splitext(basename)[0])

        if useCache is not False:
            if os.path.exists(cacheFilename):
                if os.path.getmtime(cacheFilename) >= os.path.getmtime(pdfFilename) or useCache:
                    sys.stdout.write("reading cache '%s'...\n" % cacheFilename)
                    try:
                        slides = bz2_pickle.unpickle(cacheFilename)
                    except Exception, e:
                        sys.stderr.write("FAILED to load cache (%s), re-rendering...\n" % (e, ))
        
        if slides is None:
            infos = pdf_infos.PDFInfos.create(pdfFilename)

            # if infos:
            #     pageWidthInches = numpy.diff(infos.pageBoxes()[0], axis = 0)[0,0] / 72
            #     dpi = self.slideSize()[0] / pageWidthInches

            wallClockTime = time.time()
            cpuTime = time.clock()

            pages = renderer.renderAllPages(pdfFilename, sizePX = self.slideSize(),
                                            pageCount = infos and infos.pageCount())

            frames = presentation.create_frames(pages)
            presentation.detect_navigation(frames)
            slides = presentation.Presentation(infos)
            slides.addFrames(frames)

            print "complete rendering took %.3gs. (%.3gs. real time)" % (
                time.clock() - cpuTime, time.time() - wallClockTime)

            if createCache:
                sys.stdout.write("caching in '%s'...\n" % cacheFilename)
                bz2_pickle.pickle(cacheFilename, slides)

        self.setSlides(slides)

    def setSlides(self, slides):
        self._slides = slides
        assert not self._renderers, "FIXME: delete old renderers / graphics items"
        self._renderers = [slide_renderer.SlideRenderer(s, self._slideViewport) for s in slides]
        for r in self._renderers:
            r.setLinkHandler(self.followLink)
        self._setupGrid()
        self.gotoFrame(0)

    def slides(self):
        return self._slides

    def _setupGrid(self):
        self._overviewColumnCount = min(5, int(math.ceil(math.sqrt(len(self._slides)))))

        slideLevel = numpy.zeros((len(self._slides), ), dtype = int)

        infos = self._slides.pdfInfos()
        if infos and infos.outline():
            for level, title, frameIndex in infos.outline():
                slideLevel[self._slides.frame(frameIndex).slide().slideIndex()] = level

            # prevent too many linebreaks (very fine-grained PDF outline):
            while numpy.diff(numpy.nonzero(slideLevel)[0]).mean() < self._overviewColumnCount-0.5:
                slideLevel[slideLevel == slideLevel.max()] = 0
                if slideLevel.max() == 0:
                    break # prenvent mean() of empty array (-> nan)

        x = y = col = rowHeight = 0
        lastLineBreak = previousWidth = 0
        for i, renderer in enumerate(self._renderers):
            if col > 0:
                x += PADDING_X * max(previousWidth, renderer.slide().size().width())
            
            if slideLevel[i] and lastLineBreak < i - 1:
                y += (1.0 + PADDING_Y + LINEBREAK_PADDING / slideLevel[i]) * rowHeight
                x = col = rowHeight = 0
                lastLineBreak = i
            elif col >= self._overviewColumnCount:
                y += (1.0 + PADDING_Y) * rowHeight
                x = INDENT_X * renderer.slide().size().width() if lastLineBreak else 0
                col = rowHeight = 0

            renderer.setPos(x, y)

            x += renderer.slide().size().width()
            previousWidth = renderer.slide().size().width()
            rowHeight = max(rowHeight, renderer.slide().size().height())
            col += 1

    def _updateCursor(self, animated):
        """Moves the cursor to the current renderer.  If animated is
        True, a _cursorAnimation will be set up and started, and if
        the cursor target is not fully visible, the overview will also
        be scrolled (animatedly).  The overview pos will not be
        changed if animated == False."""
        
        if self._cursor is None:
            self._cursor = QtGui.QGraphicsWidget(self._slideViewport)
            self._cursorRect = QtGui.QGraphicsRectItem(self._cursor)
            self._cursorRect.setPen(QtGui.QPen(QtCore.Qt.yellow, 25))
            self._cursorRect.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0, 100)))
            self._cursor.setZValue(-10)
            self._cursorPos = None

        r = QtCore.QRectF(p(self._currentRenderer().pos),
                          self._currentRenderer().slide().size())

        if not animated:
            self._cursor.setPos(r.topLeft())
            self._cursorRect.setRect(QtCore.QRectF(QtCore.QPointF(0, 0), r.size()))
        else:
            self._cursorAnimation = QtCore.QPropertyAnimation(self._cursor, "pos")
            self._cursorAnimation.setDuration(100)
            self._cursorAnimation.setStartValue(p(self._cursor.pos))
            self._cursorAnimation.setEndValue(r.topLeft())
            self._cursorAnimation.start()

            pres = self._presentationItem
            if not p(self._scene.sceneRect).contains(
                    r.center() * p(pres.scale) + p(pres.pos)):
                self._animateOverviewGroup(self._overviewPosForCursor(r), p(pres.scale))

    def _adjustOverviewPos(self, pos, scale):
        """adjust position in order to prevent ugly black margins"""

        # overview smaller than scene?
        if p(self._scene.sceneRect).height() > self.presentationBounds().height() * scale:
            # yes, center overview (evenly distributing black margin):
            pos.setY(0.5 * (p(self._scene.sceneRect).height() - self.presentationBounds().height() * scale))
        elif pos.y() > 0.0:
            # no, prevent black margin at top:
            pos.setY(0.0)
        else:
            # prevent black margin at bottom:
            minY = p(self._scene.sceneRect).height() - self.presentationBounds().height() * scale
            if pos.y() < minY:
                pos.setY(minY)

    def _animateOverviewGroup(self, pos, scale):
        self._adjustOverviewPos(pos, scale)

        currentGeometry = QtCore.QRectF(p(self._presentationItem.pos),
                                        QtCore.QSizeF(p(self._presentationItem.scale),
                                                      p(self._presentationItem.scale)))
        targetGeometry = QtCore.QRectF(pos, QtCore.QSizeF(scale, scale))

        self._overviewAnimation = GeometryAnimation(self._presentationItem)
        self._overviewAnimation.setStartValue(currentGeometry)
        self._overviewAnimation.setEndValue(targetGeometry)
        self._overviewAnimation.setDuration(300)
        self._overviewAnimation.setEasingCurve(QtCore.QEasingCurve.InOutCubic)
        self._overviewAnimation.finished.connect(self._resetOverviewAnimation)

        self._overviewAnimation.start()

    def _resetOverviewAnimation(self):
        if not self._overviewAnimation:
            return

        self._overviewAnimation.stop()
        self._overviewAnimation = None
        self._adjustSlideViewport()

    def _overviewScale(self):
        """Return presentation scale that fills the view width with the overview."""
        return p(self._scene.sceneRect).width() / self.presentationBounds().width()

    def _overviewPosForCursor(self, r = None):
        if r is None:
            r = self._cursor.childItems()[0].boundingRect()
            r.translate(p(self._cursor.pos))
        s = self._overviewScale()
        y = (0.5 * p(self._scene.sceneRect).height() - r.center().y() * s)

        return QtCore.QPointF(0, y)

    def showOverview(self):
        self._updateCursor(animated = False)
        self._cursorPos = None

        for r in self._renderers:
            r.showCustomContent()

        self._animateOverviewGroup(self._overviewPosForCursor(), self._overviewScale())

        self._inOverview = True
        self._adjustSlideViewport()

    def _currentFrame(self):
        """Returns current Frame object (or None, in initialization phase)."""
        if self._currentFrameIndex is None:
            return None
        return self._slides.frame(self._currentFrameIndex)

    def _currentSlideIndex(self):
        """Returns current slide index (or None, in initialization phase)."""
        frame = self._currentFrame()
        if frame is None:
            return None
        return frame.slide().slideIndex()

    def _currentRenderer(self):
        """Returns currently active SlideRenderer (or None, in initialization phase)."""
        slideIndex = self._currentSlideIndex()
        if slideIndex is None:
            return None
        return self._renderers[slideIndex]

    def _maxpectScaleAndMargin(self, frameSize):
        """Returns presentation scale and margin (for one side,
        i.e. half of the excessive space) for centering a frame of the
        given size in the current view."""
        
        windowSize = p(self._scene.sceneRect).size()
        scale = min(windowSize.width() / frameSize.width(),
                    windowSize.height() / frameSize.height())
        margin = (windowSize - scale * frameSize) / 2.0
        return scale, margin

    def gotoFrame(self, frameIndex):
        """Identifies renderer responsible for the given frame and
        lets it show that frame.  If we're in overview mode, the scene
        is zoomed in to the above renderer."""

        targetFrame = self._slides.frame(frameIndex)
        renderer = self._renderers[targetFrame.slide().slideIndex()]
        renderer.uncover()

        animated = (not self._inOverview) \
            and self._currentFrameIndex is not None

        sourceFrame = self._currentRenderer().frame() if animated else None
            
        renderer.showFrame(targetFrame.subIndex(), animateFrom = sourceFrame)

        self._currentFrameIndex = frameIndex

        scale, margin = self._maxpectScaleAndMargin(targetFrame.size())
        targetPresentationPos = QtCore.QPointF(margin.width(), margin.height()) - p(renderer.pos) * scale
        
        if not self._inOverview:
            self._presentationItem.setPos(targetPresentationPos)
            self._adjustSlideViewport()
        else:
            self._inOverview = False
            self._animateOverviewGroup(targetPresentationPos, scale)

    def _clearGotoSlide(self):
        self._gotoSlideIndex = None

    def followLink(self, link):
        if self._inOverview:
            return False
        if isinstance(link, int):
            frameIndex = link
            self.gotoFrame(frameIndex)
            self._mousePressPos = None # don't handle click again in mouseReleaseEvent
            return True
        return False

    def keyPressEvent(self, event):
        if event.text() == 'D':
            slide_renderer.toggleDebug()
            for r in self._renderers:
                r.resetItems()
        if event.text() == 'F':
            win = self._view.window()
            if win.isFullScreen():
                win.showNormal()
            else:
                win.showFullScreen()
            event.accept()
        elif event.key() in (QtCore.Qt.Key_F, QtCore.Qt.Key_L):
            r = self._currentRenderer()
            r.showFrame(0 if event.key() == QtCore.Qt.Key_F else len(r.slide()) - 1)
            event.accept()
        elif event.text() and event.text() in '0123456789':
            if self._gotoSlideIndex is None:
                self._gotoSlideIndex = 0
            self._gotoSlideIndex = self._gotoSlideIndex * 10 + int(event.text())
            self._gotoSlideTimer.start()
            event.accept()
        elif event.key() == QtCore.Qt.Key_Return:
            if self._gotoSlideIndex is not None:
                event.accept()
                slideIndex = self._gotoSlideIndex - 1
                self._gotoSlideIndex = None
                self.gotoFrame(self._slides[slideIndex].currentFrame().frameIndex())
        elif event.text() == 'Q':
            self._view.window().close()
            event.accept()
        elif event.text() == 'P':
            headerItems = sum((r.headerItems() for r in self._renderers), [])
            footerItems = sum((r.footerItems() for r in self._renderers), [])
            if headerItems and footerItems:
                onoff = headerItems[0].isVisible() + 2*footerItems[0].isVisible()
                onoff = (onoff + 1) % 4
                for headerItem in headerItems:
                    headerItem.setVisible(onoff % 2)
                for footerItem in footerItems:
                    footerItem.setVisible(onoff // 2)
                event.accept()
            elif headerItems or footerItems:
                items = headerItems or footerItems
                onoff = not items[0].isVisible()
                for item in items:
                    item.setVisible(onoff)
                event.accept()
            else:
                sys.stderr.write('DEBUG: no header/footer items found.\n')

        if event.isAccepted():
            return

        if self._inOverview:
            if event.key() in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Left,
                               QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                self._handleCursorKeyInOverview(event)
                event.accept()
            elif event.key() in (QtCore.Qt.Key_Home, ):
                if self._currentFrameIndex:
                    self._currentFrameIndex = 0
                    self._updateCursor(animated = True)
                    event.accept()
            elif event.text() == 'U':
                for renderer in self._renderers:
                    renderer.uncoverAll()
                event.accept()
            elif event.text() == 'R':
                for renderer in self._renderers:
                    renderer.showFrame(0)
                    renderer.uncover(False)
                if self._currentFrameIndex:
                    self._currentFrameIndex = 0
                    self._updateCursor(animated = True)
                event.accept()
            elif event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Return, QtCore.Qt.Key_Space):
                self.gotoFrame(self._currentFrameIndex)
                event.accept()
        else:
            if event.key() in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown):
                if self._currentFrameIndex < self._slides.frameCount() - 1:
                    self.gotoFrame(self._currentFrameIndex + 1)
                    event.accept()
            elif event.key() in (QtCore.Qt.Key_Backspace, QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp):
                if self._currentFrameIndex > 0:
                    self.gotoFrame(self._currentFrameIndex - 1)
                    event.accept()
            elif event.key() in (QtCore.Qt.Key_Home, ):
                if self._currentFrameIndex:
                    self.gotoFrame(0)
                    event.accept()
            elif event.key() in (QtCore.Qt.Key_Tab, ):
                self.showOverview()
                event.accept()

    def _handleCursorKeyInOverview(self, event):
        item = self._currentRenderer()
        r = item.sceneBoundingRect()
        if self._cursorPos is None:
            self._cursorPos = r.center()

        desiredSlideIndex = None

        # naming of variables follows downwards-case, other cases are rotated:
        if event.key() == QtCore.Qt.Key_Down:
            ge = operator.ge
            bottom = r.bottom()
            getTop = QtCore.QRectF.top
            getX = QtCore.QPointF.x
            getY = QtCore.QPointF.y
            setY = QtCore.QPointF.setY
            sortDirection = 1 # ascending Y
            mustOverlapInY = False
        elif event.key() == QtCore.Qt.Key_Up:
            ge = operator.le
            bottom = r.top()
            getTop = QtCore.QRectF.bottom
            getX = QtCore.QPointF.x
            getY = QtCore.QPointF.y
            setY = QtCore.QPointF.setY
            sortDirection = -1 # descending Y
            mustOverlapInY = False
        elif event.key() == QtCore.Qt.Key_Right:
            ge = operator.ge
            bottom = r.right()
            getTop = QtCore.QRectF.left
            getX = QtCore.QPointF.y
            getY = QtCore.QPointF.x
            setY = QtCore.QPointF.setX
            sortDirection = 1 # ascending X
            mustOverlapInY = True
        elif event.key() == QtCore.Qt.Key_Left:
            ge = operator.le
            bottom = r.left()
            getTop = QtCore.QRectF.right
            getX = QtCore.QPointF.y
            getY = QtCore.QPointF.x
            setY = QtCore.QPointF.setX
            sortDirection = -1 # descending X
            mustOverlapInY = True

        # handle all cases, with naming of variables following downwards-case (see above)
        belowItems = []
        for otherItem in self._renderers:
            r2 = otherItem.sceneBoundingRect()
            if ge(getTop(r2), bottom):
                if mustOverlapInY:
                    if r2.bottom() < r.top() or r2.top() > r.bottom():
                        continue # don't jump between rows
                c2 = r2.center()
                # sort by Y first (moving as few as possible in cursor dir.),
                # then sort by difference in X to "current pos"
                # (self._cursorPos is similar to r.center(), but allows to
                # move over rows with fewer items without losing the original
                # x position)
                belowItems.append((sortDirection * getY(c2),
                                   abs(getX(c2) - getX(self._cursorPos)),
                                   otherItem))

        if belowItems:
            belowItems.sort()
            sortY, _, desiredSlide = belowItems[0]
            centerY = sortDirection * sortY
            desiredSlideIndex = self._renderers.index(desiredSlide)
            setY(self._cursorPos, centerY)
        else:
            currentSlideIndex = self._currentSlideIndex()
            if event.key() == QtCore.Qt.Key_Right:
                if currentSlideIndex < len(self._slides)-1:
                    desiredSlideIndex = currentSlideIndex + 1
            elif event.key() == QtCore.Qt.Key_Left:
                if currentSlideIndex > 0:
                    desiredSlideIndex = currentSlideIndex - 1

        if desiredSlideIndex is not None:
            self._currentFrameIndex = self._slides[desiredSlideIndex].currentFrame().frameIndex()
            self._updateCursor(animated = True)


def start(view = None, show = True):
    global app
    hasApp = QtGui.QApplication.instance()
    if not hasApp:
        app = QtGui.QApplication(sys.argv)
    else:
        app = hasApp
    app.setApplicationName("PDF Decanter")
    app.setApplicationVersion(__version__)

    result = PDFDecanter(view)
    result.hadEventLoop = hasattr(app, '_in_event_loop') and app._in_event_loop # IPython support

    if show and view is None:
        result.view().show()
        if sys.platform == "darwin":
            result.view().raise_()

    return result
