from dynqt import QtCore, QtGui, QtOpenGL

import numpy, os, sys
import pdftoppm_renderer, slide

__version__ = "0.1"

w, h = 1024, 768

OVERVIEW_COLS = 5
MARGIN_X = 30
MARGIN_Y = 24
BLEND_DURATION = 150
USE_GL = True # False
USE_CACHING = True # False

if USE_GL:
    try:
        from OpenGL import GL
    except ImportError:
        USE_GL = False
        sys.stderr.write("WARNING: OpenGL could not be loaded, running without GL...\n")

class PDFPresenter(QtCore.QObject):
    def __init__(self, view = None):
        QtCore.QObject.__init__(self)

        if view is None:
            view = QtGui.QGraphicsView()
            view.resize(w, h)
        self._view = view

        view.installEventFilter(self)

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

        self._slideViewport = QtGui.QGraphicsRectItem(QtCore.QRectF(0, 0, w, h))
        self._scene.addItem(self._slideViewport)
        self._slideViewport.setFlag(QtGui.QGraphicsItem.ItemClipsChildrenToShape)

        self._presentationItem = QtGui.QGraphicsWidget(self._slideViewport)
        self._group = QtGui.QGraphicsItemGroup(self._presentationItem)

        self._cursor = QtGui.QGraphicsWidget(self._group)
        cursorRect = self._scene.addRect(self._scene.sceneRect())
        cursorRect.setPen(QtGui.QPen(QtCore.Qt.yellow, 25))
        cursorRect.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0, 100)))
        cursorRect.setParentItem(self._cursor)

        self._renderers = None
        self._currentFrameIndex = None
        self._slideAnimation = None

        self._gotoSlideIndex = None
        self._gotoSlideTimer = QtCore.QTimer(self)
        self._gotoSlideTimer.setSingleShot(True)
        self._gotoSlideTimer.setInterval(1000)
        self._gotoSlideTimer.timeout.connect(self._clearGotoSlide)

        self._inOverview = False

    def view(self):
        return self._view

    def slideSize(self):
        return w, h

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            self.keyPressEvent(event)
            if event.isAccepted():
                return True
        return QtCore.QObject.eventFilter(self, obj, event)

    # def resizeEvent(self, e):
    #     #self.fitInView(0, 0, w, h, QtCore.Qt.KeepAspectRatio)
    #     w, h = self.slideSize()
    #     factor = min(float(e.size().width()) / w,
    #                  float(e.size().height()) / h)
    #     self.resetMatrix()
    #     self.scale(factor, factor)
    #     return QtGui.QGraphicsView.resizeEvent(self, e)

    def loadPDF(self, pdfFilename):
        raw_frames = list(pdftoppm_renderer.renderAllPages(pdfFilename, self.slideSize()))

        slides = slide.stack_frames(raw_frames)

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
        assert not self._renderers, "FIXME: delete old renderers / graphisc items"
        self._renderers = [slide.SlideRenderer(s, self._group) for s in slides]
        self._setupGrid()
        self.gotoFrame(0, animated = False)

    def _setupGrid(self):
        for i, renderer in enumerate(self._renderers):
            renderer.setPos((w + MARGIN_X) * (i % OVERVIEW_COLS),
                            (h + MARGIN_Y) * (i / OVERVIEW_COLS))
            self._group.addToGroup(renderer)

    def _updateCursor(self, animated):
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
            minY = self._scene.sceneRect().height() - self._group.boundingRect().height() * scale
            if pos.y() < minY:
                pos.setY(minY)

        # FIXME: clear up / reuse QObject:
        self._overviewAnimation = QtCore.QParallelAnimationGroup()

        posAnim = QtCore.QPropertyAnimation(self._presentationItem, "pos", self._overviewAnimation)
        posAnim.setDuration(200)
        posAnim.setStartValue(self._presentationItem.pos())
        posAnim.setEndValue(pos)

        scaleAnim = QtCore.QPropertyAnimation(self._presentationItem, "scale", self._overviewAnimation)
        scaleAnim.setDuration(200)
        scaleAnim.setStartValue(self._presentationItem.scale())
        scaleAnim.setEndValue(scale)

        self._overviewAnimation.addAnimation(posAnim)
        self._overviewAnimation.addAnimation(scaleAnim)
        self._overviewAnimation.start()

    def _overviewScale(self):
        return float(self._scene.sceneRect().width()) / self._group.boundingRect().width()

    def _overviewPosForCursor(self, r = None):
        if r is None:
            r = self._cursor.childItems()[0].boundingRect()
            r.moveTo(self._cursor.pos())
        s = self._overviewScale()
        y = (0.5 * self._scene.sceneRect().height() - r.center().y() * s)

        return QtCore.QPointF(0, y)

    def showOverview(self):
        # self._setupGrid()
        self._resetSlideAnimation()

        self._updateCursor(animated = False)

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

    def keyPressEvent(self, event):
        event.ignore() # assume not handled for now

        if event.key() in (QtCore.Qt.Key_F, QtCore.Qt.Key_L):
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
                               self._renderers[slideIndex].currentFrame(), animated = False)
        elif event.text() == 'P':
            onoff = not self._currentRenderer().navigationItem().isVisible()
            for r in self._renderers:
                r.navigationItem().setVisible(onoff)
            event.accept()

        if event.isAccepted():
            return

        if self._inOverview:
            if event.key() in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Left,
                               QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                currentSlideIndex, _ = self._frame2Slide[self._currentFrameIndex]
                desiredSlideIndex = currentSlideIndex + {
                    QtCore.Qt.Key_Right : +1,
                    QtCore.Qt.Key_Left  : -1,
                    QtCore.Qt.Key_Down  : +OVERVIEW_COLS,
                    QtCore.Qt.Key_Up    : -OVERVIEW_COLS}[event.key()]

                desiredSlideIndex = max(0, min(desiredSlideIndex, len(self._slides)-1))
                self._currentFrameIndex = (
                    self._slide2Frame[desiredSlideIndex] +
                    self._renderers[desiredSlideIndex].currentFrame())

                self._updateCursor(animated = True)
                event.accept()
            elif event.key() in (QtCore.Qt.Key_Home, ):
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

    cacheFilename = "/tmp/pdf_presenter_cache_%s.h5" % (pdfFilename.replace("/", "!"), )

    if USE_CACHING and not 'slides' in globals():
        import cache
        if os.path.exists(cacheFilename):
            if os.path.getmtime(cacheFilename) >= os.path.getmtime(pdfFilename):
                slides = cache.readSlides(cacheFilename)

    if not 'slides' in globals() or slides is None:
        if not 'raw_frames' in globals():
            raw_frames = list(pdftoppm_renderer.renderAllPages(pdfFilename, (w, h)))

        slides = slide.stack_frames(raw_frames)
        pixelCount = sum(s.pixelCount() for s in slides)
        rawCount = len(raw_frames) * numpy.prod(raw_frames[0].shape[:2])
        print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

        if USE_CACHING:
            print "caching in '%s'..." % cacheFilename
            if os.path.exists(cacheFilename):
                os.unlink(cacheFilename)
            cache.writeSlides(cacheFilename, slides)

    g.setSlides(slides)
    
    if not g.hadEventLoop:
        sys.exit(QtGui.qApp.exec_())
