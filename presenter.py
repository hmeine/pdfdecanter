#!/usr/bin/env python
from dynqt import QtCore, QtGui, QtOpenGL

import numpy, os, sys, tempfile, math, operator
import pdftoppm_renderer, pdf_infos, bz2_pickle, slide

__version__ = "0.1"

w, h = 1024, 768

BLEND_DURATION = 150
USE_GL = True # False
USE_CACHING = True # False

PADDING_X = 30
PADDING_Y = 24
LINEBREAK_PADDING = 3.5 * PADDING_Y
INDENT_X = 0 # w / 8

if USE_GL:
    try:
        from OpenGL import GL
    except ImportError:
        USE_GL = False
        sys.stderr.write("WARNING: OpenGL could not be loaded, running without GL...\n")


class GeometryAnimation(QtCore.QVariantAnimation):
    def __init__(self, item, parent = None):
        QtCore.QVariantAnimation.__init__(self, parent)
        self._item = item

    def updateCurrentValue(self, value):
        self._item.setPos(value.topLeft())
        self._item.setScale(value.width())


class PDFPresenter(QtCore.QObject):
    def __init__(self, view = None):
        QtCore.QObject.__init__(self)

        if view is None:
            view = QtGui.QGraphicsView()
            view.resize(w, h)
        self._view = view

        self._view.installEventFilter(self)

        self._view.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

        self._view.setFrameStyle(QtGui.QFrame.NoFrame)
        self._view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        if USE_GL:
            self._view.setViewport(QtOpenGL.QGLWidget(QtOpenGL.QGLFormat(QtOpenGL.QGL.SampleBuffers)))
            self._view.setViewportUpdateMode(QtGui.QGraphicsView.FullViewportUpdate)

        if view.scene() is not None:
            self._scene = view.scene()
            self._scene.setSceneRect(0, 0, w, h)
        else:
            self._scene = QtGui.QGraphicsScene(0, 0, w, h)
            self._view.setScene(self._scene)
        self._scene.setBackgroundBrush(QtCore.Qt.black)
        self._scene.selectionChanged.connect(self._selectionChanged)
        self._selectionChangeComesFromButtonRelease = False
        self._scene.installEventFilter(self) # for MouseButtonRelease events

        self._slideViewport = QtGui.QGraphicsRectItem(QtCore.QRectF(0, 0, w, h))
        self._scene.addItem(self._slideViewport)
        self._slideViewport.setFlag(QtGui.QGraphicsItem.ItemClipsChildrenToShape)

        self._presentationItem = QtGui.QGraphicsWidget(self._slideViewport)

        self._cursor = None

        self._renderers = None
        self._currentFrameIndex = None
        self._slideAnimation = None

        self._gotoSlideIndex = None
        self._gotoSlideTimer = QtCore.QTimer(self)
        self._gotoSlideTimer.setSingleShot(True)
        self._gotoSlideTimer.setInterval(1000)
        self._gotoSlideTimer.timeout.connect(self._clearGotoSlide)

        self._clearMouseReleaseFlagTimer = QtCore.QTimer(self)
        self._clearMouseReleaseFlagTimer.setSingleShot(True)
        self._clearMouseReleaseFlagTimer.setInterval(100)
        self._clearMouseReleaseFlagTimer.timeout.connect(self._clearMouseReleaseFlag)

        self._hideMouseTimer = QtCore.QTimer(self)
        self._hideMouseTimer.setSingleShot(False)
        self._hideMouseTimer.setInterval(1000)
        self._hideMouseTimer.timeout.connect(self._hideMouse)
        self._hideMouseTimer.start()

        self._view.viewport().setMouseTracking(True)
        self._view.viewport().installEventFilter(self)

        self._inOverview = False

    def view(self):
        return self._view

    def slideSize(self):
        return w, h

    def presentationBounds(self):
        result = QtCore.QRectF()
        for r in self._renderers:
            br = r.boundingRect()
            br.translate(r.pos())
            result |= br
        return result

    def _selectionChanged(self):
        selectedItems = self._scene.selectedItems()
        if not selectedItems:
            return

        # we need to get selectionChanged events also for multiple
        # clicks on the same slide, so unselect here:
        self._scene.setSelectionArea(QtGui.QPainterPath())

        if self._selectionChangeComesFromButtonRelease:
            self._selectionChangeComesFromButtonRelease = False
            return

        if not self._inOverview:
            if self._currentFrameIndex < len(self._frame2Slide) - 1:
                self.gotoFrame(self._currentFrameIndex + 1, animated = True)
        else:
            selectedItem, = selectedItems
            slideIndex = self._renderers.index(selectedItem)
            self.gotoFrame(self._slide2Frame[slideIndex] +
                           self._renderers[slideIndex].currentFrame(), animated = False)

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
        elif obj is self._scene:
            if event.type() == QtCore.QEvent.GraphicsSceneMouseRelease:
                self.mouseReleaseEvent(event)
        if event.isAccepted():
            return True
        return False

    def resizeEvent(self, e):
        w, h = self.slideSize()
        factor = min(float(e.size().width()) / w,
                     float(e.size().height()) / h)
        self._view.resetMatrix()
        self._view.scale(factor, factor)

    def mouseMoveEvent(self, e):
        self._view.unsetCursor()
        self._hideMouseTimer.start()

    def _hideMouse(self):
        self._view.setCursor(QtCore.Qt.BlankCursor)

    def mouseReleaseEvent(self, e):
        self._selectionChangeComesFromButtonRelease = True
        self._clearMouseReleaseFlagTimer.start()

    def _clearMouseReleaseFlag(self):
        if self._selectionChangeComesFromButtonRelease:
            #print "DEBUG: mouse button release flag still active, clearing..."
            self._selectionChangeComesFromButtonRelease = False

    def loadPDF(self, pdfFilename, cacheFilename = None):
        slides = None

        if cacheFilename:
            if cacheFilename is True:
                cacheFilename = os.path.join(
                    tempfile.gettempdir(),
                    "pdf_presenter_cache_%s.bz2" % (os.path.abspath(pdfFilename).replace("/", "!"), ))
                sys.stderr.write('ATTENTION! unpickling from system-wide tempdir is a security risk!\n')

            if os.path.exists(cacheFilename):
                # FIXME: handle Presentation.FORMAT_VERSION
                if os.path.getmtime(cacheFilename) >= os.path.getmtime(pdfFilename):
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

            raw_frames = list(pdftoppm_renderer.renderAllPages(pdfFilename, sizePX = self.slideSize(),
                                                               pageCount = infos and infos.pageCount()))

            slides = slide.stack_frames(raw_frames)
            slides.setPDFInfos(infos)

            if cacheFilename:
                sys.stdout.write("caching in '%s'...\n" % cacheFilename)
                bz2_pickle.pickle(cacheFilename, slides)

        self.setSlides(slides)

    def _slidesChanged(self):
        self._frame2Slide = []
        self._slide2Frame = []
        for i, s in enumerate(self._slides):
            self._slide2Frame.append(len(self._frame2Slide))
            self._frame2Slide.extend([(i, j) for j in range(len(s))])

    def setSlides(self, slides):
        self._slides = slides
        self._slidesChanged()
        assert not self._renderers, "FIXME: delete old renderers / graphics items"
        self._renderers = [slide.SlideRenderer(s, self._presentationItem) for s in slides]
        for r in self._renderers:
            r.setLinkHandler(self.followLink)
        self._setupGrid()
        self.gotoFrame(0, animated = False)

    def _setupGrid(self):
        self._overviewColumnCount = min(5, int(math.ceil(math.sqrt(len(self._slides)))))

        slideLevel = numpy.zeros((len(self._slides), ), dtype = int)

        infos = self._slides.pdfInfos()
        if infos and infos.outline():
            for level, title, frameIndex in infos.outline():
                slideLevel[self._frame2Slide[frameIndex][0]] = level

            while numpy.diff(numpy.nonzero(slideLevel)[0]).mean() < self._overviewColumnCount:
                slideLevel[slideLevel == slideLevel.max()] = 0

        x = y = col = 0
        lastLineBreak = 0
        for i, renderer in enumerate(self._renderers):
            if slideLevel[i] and lastLineBreak < i - 1:
                y += (h + LINEBREAK_PADDING)
                x = col = 0
                lastLineBreak = i
            elif col >= self._overviewColumnCount:
                y += (h + PADDING_Y)
                x = INDENT_X if lastLineBreak else 0
                col = 0

            renderer.setPos(x, y)

            x += (w + PADDING_X)
            col += 1

    def _updateCursor(self, animated):
        if self._cursor is None:
            self._cursor = QtGui.QGraphicsWidget(self._presentationItem)
            cursorRect = QtGui.QGraphicsRectItem(self._scene.sceneRect(), self._cursor)
            cursorRect.setPen(QtGui.QPen(QtCore.Qt.yellow, 25))
            cursorRect.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0, 100)))
            self._cursor.setZValue(-10)
            self._cursorPos = None

        r = QtCore.QRectF(self._currentRenderer().pos(),
                          self._currentRenderer().slide().size())

        if not animated:
            self._cursor.setPos(r.topLeft())
        else:
            self._cursorAnimation = QtCore.QPropertyAnimation(self._cursor, "pos")
            self._cursorAnimation.setDuration(100)
            self._cursorAnimation.setStartValue(self._cursor.pos())
            self._cursorAnimation.setEndValue(r.topLeft())
            self._cursorAnimation.start()

            pres = self._presentationItem
            if not self._scene.sceneRect().contains(
                    r.center() * pres.scale() + pres.pos()):
                self._animateOverviewGroup(self._overviewPosForCursor(r), pres.scale())

    def _animateOverviewGroup(self, pos, scale):
        if pos.y() > 0.0:
            pos.setY(0.0)
        else:
            minY = self._scene.sceneRect().height() - self.presentationBounds().height() * scale
            if pos.y() < minY:
                pos.setY(minY)

        currentGeometry = QtCore.QRectF(self._presentationItem.pos(),
                                        QtCore.QSizeF(self._presentationItem.scale(),
                                                      self._presentationItem.scale()))
        targetGeometry = QtCore.QRectF(pos, QtCore.QSizeF(scale, scale))

        # FIXME: clear up / reuse QObject:
        self._overviewAnimation = GeometryAnimation(self._presentationItem)
        self._overviewAnimation.setStartValue(currentGeometry)
        self._overviewAnimation.setEndValue(targetGeometry)
        self._overviewAnimation.setDuration(300)
        self._overviewAnimation.setEasingCurve(QtCore.QEasingCurve.InOutCubic)

        self._overviewAnimation.start()

    def _overviewScale(self):
        return float(self._scene.sceneRect().width()) / self.presentationBounds().width()

    def _overviewPosForCursor(self, r = None):
        if r is None:
            r = self._cursor.childItems()[0].boundingRect()
            r.translate(self._cursor.pos())
        s = self._overviewScale()
        y = (0.5 * self._scene.sceneRect().height() - r.center().y() * s)

        return QtCore.QPointF(0, y)

    def showOverview(self):
        # self._setupGrid()
        self._resetSlideAnimation()

        self._updateCursor(animated = False)
        self._cursorPos = None

        self._animateOverviewGroup(self._overviewPosForCursor(), self._overviewScale())

        self._inOverview = True

    def _currentRenderer(self):
        slideIndex, _ = self._frame2Slide[self._currentFrameIndex]
        return self._renderers[slideIndex]

    def _resetSlideAnimation(self):
        """clean up previously offset items"""
        if self._slideAnimation is not None:
            self._slideAnimation.stop()
            self._slideAnimation = None
            r1, r2, movedRenderer, oldPos = self._animatedRenderers
            r1.contentItem().setPos(QtCore.QPointF(0, 0))
            r2.contentItem().setPos(QtCore.QPointF(0, 0))
            movedRenderer.setPos(oldPos)
            movedRenderer._backgroundItem().show()
            r1.navigationItem().setOpacity(1.0)
            r2.navigationItem().setOpacity(1.0)
            if not self._inOverview:
                self._presentationItem.setPos(-r2.pos())

    def gotoFrame(self, frameIndex, animated = False):
        self._resetSlideAnimation()

        slideIndex, subFrame = self._frame2Slide[frameIndex]
        renderer = self._renderers[slideIndex]
        renderer.uncover()
        renderer.showFrame(subFrame)

        if animated:
            previousRenderer = self._currentRenderer()

            if previousRenderer is not renderer:
                if frameIndex > self._currentFrameIndex:
                    topRenderer = renderer
                    bottomRenderer = previousRenderer
                else:
                    topRenderer = previousRenderer
                    bottomRenderer = renderer

                oldPos = topRenderer.pos()
                topRenderer.setPos(bottomRenderer.pos())
                topRenderer._backgroundItem().hide()

                # store information for later reset:
                self._animatedRenderers = (previousRenderer, renderer, topRenderer, oldPos)

                self._slideAnimation = QtCore.QParallelAnimationGroup()

                offset = w if frameIndex > self._currentFrameIndex else -w

                slideOutAnim = QtCore.QPropertyAnimation(
                    previousRenderer.contentItem(), "pos", self._slideAnimation)
                slideOutAnim.setDuration(250)
                slideOutAnim.setStartValue(QtCore.QPoint(0, 0))
                slideOutAnim.setEndValue(QtCore.QPoint(-offset, 0))

                slideInAnim = QtCore.QPropertyAnimation(
                    renderer.contentItem(), "pos", self._slideAnimation)
                slideInAnim.setDuration(250)
                slideInAnim.setStartValue(QtCore.QPoint(offset, 0))
                slideInAnim.setEndValue(QtCore.QPoint(0, 0))

                blendAnimation1 = QtCore.QPropertyAnimation(
                    renderer.navigationItem(), "opacity", self._slideAnimation)
                blendAnimation1.setDuration(BLEND_DURATION)
                blendAnimation1.setStartValue(0.0)
                blendAnimation1.setEndValue(1.0)

                blendAnimation2 = QtCore.QPropertyAnimation(
                    previousRenderer.navigationItem(), "opacity", self._slideAnimation)
                blendAnimation2.setDuration(BLEND_DURATION)
                blendAnimation2.setStartValue(1.0)
                blendAnimation2.setEndValue(0.0)

                blendSequence = QtCore.QSequentialAnimationGroup(self._slideAnimation)
                blendSequence.addAnimation(blendAnimation1)
                blendSequence.addAnimation(blendAnimation2)

                self._slideAnimation.addAnimation(slideOutAnim)
                self._slideAnimation.addAnimation(slideInAnim)
                self._slideAnimation.addAnimation(blendSequence)
                self._slideAnimation.start()
            elif animated != 'slide':
                self._blendAnimation = QtCore.QPropertyAnimation(
                    renderer.frameItem(renderer.currentFrame()), "opacity")
                self._blendAnimation.setDuration(BLEND_DURATION)
                self._blendAnimation.setStartValue(0.0)
                self._blendAnimation.setEndValue(1.0)
                self._blendAnimation.start()

        self._currentFrameIndex = frameIndex

        if not self._inOverview:
            self._presentationItem.setPos(-renderer.pos())
        else:
            self._inOverview = False
            self._animateOverviewGroup(-renderer.pos(), 1.0)

    def _clearGotoSlide(self):
        self._gotoSlideIndex = None

    def followLink(self, link):
        if isinstance(link, int):
            frameIndex = link
            self.gotoFrame(frameIndex, animated = True)

    def keyPressEvent(self, event):
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
                self.gotoFrame(self._slide2Frame[slideIndex] +
                               self._renderers[slideIndex].currentFrame(), animated = True)
        elif event.text() == 'Q':
            self._view.window().close()
            event.accept()
        elif event.text() == 'P':
            headerItem, footerItem = self._currentRenderer().navigationItem().childItems()
            onoff = headerItem.isVisible() + 2*footerItem.isVisible()
            onoff = (onoff + 1) % 4
            for r in self._renderers:
                headerItem, footerItem = r.navigationItem().childItems()
                headerItem.setVisible(onoff % 2)
                footerItem.setVisible(onoff / 2)
            event.accept()

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
                    renderer.uncover()
                event.accept()
            elif event.text() == 'R':
                for renderer in self._renderers:
                    renderer.showFrame(0)
                    renderer.uncover(False)
                if self._currentFrameIndex:
                    self._currentFrameIndex = 0
                    self._updateCursor(animated = True)
                event.accept()
            elif event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Return):
                self.gotoFrame(self._currentFrameIndex)
                event.accept()
        else:
            if event.key() in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown):
                if self._currentFrameIndex < len(self._frame2Slide) - 1:
                    self.gotoFrame(self._currentFrameIndex + 1, animated = True)
                    event.accept()
            elif event.key() in (QtCore.Qt.Key_Backspace, QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp):
                if self._currentFrameIndex > 0:
                    self.gotoFrame(self._currentFrameIndex - 1, animated = 'slide')
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
            currentSlideIndex, _ = self._frame2Slide[self._currentFrameIndex]
            if event.key() == QtCore.Qt.Key_Right:
                if currentSlideIndex < len(self._slides)-1:
                    desiredSlideIndex = currentSlideIndex + 1
            elif event.key() == QtCore.Qt.Key_Left:
                if currentSlideIndex > 0:
                    desiredSlideIndex = currentSlideIndex - 1

        if desiredSlideIndex is not None:
            self._currentFrameIndex = (
                self._slide2Frame[desiredSlideIndex] +
                self._renderers[desiredSlideIndex].currentFrame())
            self._updateCursor(animated = True)


def start(view = None):
    global app
    hasApp = QtGui.QApplication.instance()
    if not hasApp:
        import sys
        app = QtGui.QApplication(sys.argv)
    else:
        app = hasApp
    app.setApplicationName("PDF Presenter")
    app.setApplicationVersion(__version__)

    result = PDFPresenter(view)
    result.hadEventLoop = hasattr(app, '_in_event_loop') and app._in_event_loop # IPython support
    return result


if __name__ == "__main__":
    import sys

    g = start()
    
    g.view().show()
    if sys.platform == "darwin":
        g.view().raise_()

    from optparse import OptionParser
    op = OptionParser(usage = "%prog [options] <filename1> <filename2>")
    options, args = op.parse_args()

    pdfFilename, = args

    if not 'slides' in globals():
        g.loadPDF(pdfFilename, cacheFilename = USE_CACHING)

        pixelCount = sum(s.pixelCount() for s in g._slides)
        ss = g._slides[0].size()
        rawCount = len(g._frame2Slide) * ss.width() * ss.height()
        print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

    if not g.hadEventLoop:
        sys.exit(QtGui.qApp.exec_())
