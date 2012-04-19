import sip
sip.setapi("QString", 2)
from PyQt4 import QtCore, QtGui, QtOpenGL

import numpy, os
import pdftoppm_renderer, slide, cache

__version__ = "0.1"

w, h = 1024, 768

OVERVIEW_COLS = 5
MARGIN_X = 30
MARGIN_Y = 24
BLEND_DURATION = 150
USE_GL = True # False

if USE_GL:
    try:
        from OpenGL import GL
    except ImportError:
        USE_GL = False

class PDFPresenter(QtGui.QGraphicsView):
    def __init__(self):
        QtGui.QGraphicsView.__init__(self)
        self.resize(w, h)

        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

        self.setFrameStyle(QtGui.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        if USE_GL:
            self.setViewport(QtOpenGL.QGLWidget(QtOpenGL.QGLFormat(QtOpenGL.QGL.SampleBuffers)))
            self.setViewportUpdateMode(QtGui.QGraphicsView.FullViewportUpdate)

        self._scene = QtGui.QGraphicsScene(0, 0, w, h)
        self._scene.setBackgroundBrush(QtCore.Qt.black)
        self.setScene(self._scene)

        self._slideViewport = QtGui.QGraphicsRectItem(QtCore.QRectF(0, 0, w, h))
        self._scene.addItem(self._slideViewport)
        self._slideViewport.setFlag(QtGui.QGraphicsItem.ItemClipsChildrenToShape)

        self._presentationItem = QtGui.QGraphicsWidget(self._slideViewport)
        self._group = QtGui.QGraphicsItemGroup(self._presentationItem)

        self._cursor = self._scene.addRect(self._scene.sceneRect())
        self._cursor.setPen(QtGui.QPen(QtCore.Qt.yellow, 25))
        self._cursor.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0, 100)))
        self._cursor.setParentItem(self._group)

        self._renderers = None
        self._currentFrameIndex = None
        self._slideAnimation = None

        self._gotoSlideIndex = None
        self._gotoSlideTimer = QtCore.QTimer(self)
        self._gotoSlideTimer.setSingleShot(True)
        self._gotoSlideTimer.setInterval(1000)
        self._gotoSlideTimer.timeout.connect(self._clearGotoSlide)

        self._inOverview = False

    def resizeEvent(self, e):
        #self.fitInView(0, 0, w, h, QtCore.Qt.KeepAspectRatio)
        factor = min(float(e.size().width()) / w,
                     float(e.size().height()) / h)
        self.resetMatrix()
        self.scale(factor, factor)
        return QtGui.QGraphicsView.resizeEvent(self, e)

    def setSlides(self, slides):
        self._slides = slides
        assert not self._renderers, "FIXME: delete old renderers / graphisc items"
        self._renderers = [slide.SlideRenderer(s, self._group, self) for s in slides]
        self._setupGrid()

        self._frame2Slide = []
        self._slide2Frame = []
        for i, s in enumerate(slides):
            self._slide2Frame.append(len(self._frame2Slide))
            self._frame2Slide.extend([(i, j) for j in range(len(s))])

        self.gotoFrame(0, animated = False)

    def _setupGrid(self):
        for i, renderer in enumerate(self._renderers):
            slideItem = renderer.slideItem()
            slideItem.setPos((w + MARGIN_X) * (i % OVERVIEW_COLS),
                             (h + MARGIN_Y) * (i / OVERVIEW_COLS))
            self._group.addToGroup(slideItem)

    def _cursorRect(self):
        return self._cursor.rect()

    def _setCursorRect(self, r):
        self._cursor.setRect(r)

    cursorRect = QtCore.pyqtProperty(QtCore.QRectF, _cursorRect, _setCursorRect)

    def _updateCursor(self, animated):
        r = QtCore.QRectF(self._currentSlideItem().pos(),
                          self._currentRenderer().slide().size())

        if not animated:
            self._cursor.setRect(r)
        else:
            self._cursorAnimation = QtCore.QPropertyAnimation(self, "cursorRect")
            self._cursorAnimation.setDuration(100)
            self._cursorAnimation.setStartValue(self._cursorRect())
            self._cursorAnimation.setEndValue(r)
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
            r = self._cursor.boundingRect()
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

    def _currentSlideItem(self):
        return self._currentRenderer().slideItem()

    def _resetSlideAnimation(self):
        """clean up previously offset items"""
        if self._slideAnimation is not None:
            self._slideAnimation.stop()
            self._slideAnimation = None
            r1, r2, movedRenderer, oldPos = self._animatedRenderers
            r1.contentItem().setPos(QtCore.QPointF(0, 0))
            r2.contentItem().setPos(QtCore.QPointF(0, 0))
            movedRenderer.slideItem().setPos(oldPos)
            movedRenderer._backgroundItem().show()
            r1.navigationItem().setOpacity(1.0)
            r2.navigationItem().setOpacity(1.0)
            if not self._inOverview:
                self._presentationItem.setPos(-r2.slideItem().pos())

    def gotoFrame(self, frameIndex, animated = False):
        self._resetSlideAnimation()

        slideIndex, subFrame = self._frame2Slide[frameIndex]
        renderer = self._renderers[slideIndex]
        renderer.uncover()
        slideItem = renderer.showFrame(subFrame)

        if animated:
            previousRenderer = self._currentRenderer()

            if previousRenderer is not renderer:
                if frameIndex > self._currentFrameIndex:
                    topRenderer = renderer
                    bottomRenderer = previousRenderer
                else:
                    topRenderer = previousRenderer
                    bottomRenderer = renderer

                oldPos = topRenderer.slideItem().pos()
                topRenderer.slideItem().setPos(bottomRenderer.slideItem().pos())
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
            self._presentationItem.setPos(-slideItem.pos())
        else:
            self._inOverview = False
            self._animateOverviewGroup(-slideItem.pos(), 1.0)

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
            elif event.key() in (QtCore.Qt.Key_P, ):
                nav = self._currentRenderer().navigationItem()
                nav.setVisible(not nav.isVisible())
                event.accept()

        if not event.isAccepted():
            QtGui.QGraphicsView.keyPressEvent(self, event)


def start():
    global app
    hasApp = QtGui.QApplication.instance()
    if not hasApp:
        import sys
        app = QtGui.QApplication(sys.argv)
    else:
        app = hasApp
    app.setApplicationName("PDF Presenter")
    app.setApplicationVersion(__version__)

    result = PDFPresenter()
    result.hadEventLoop = hasattr(app, '_in_event_loop') and app._in_event_loop # IPython support
    return result


if __name__ == "__main__":
    import sys

    g = start()
    
    g.show()
    if sys.platform == "darwin":
        g.raise_()

    from optparse import OptionParser
    op = OptionParser(usage = "%prog [options] <filename1> <filename2>")
    options, args = op.parse_args()

    pdfFilename, = args

    cacheFilename = "/tmp/pdf_presenter_cache_%s.h5" % (pdfFilename.replace("/", "!"), )

    if not 'slides' in globals():
        if os.path.exists(cacheFilename):
            if os.path.getmtime(cacheFilename) >= os.path.getmtime(pdfFilename):
                slides = cache.readSlides(cacheFilename)

    if not 'slides' in globals():
        if not 'raw_frames' in globals():
            raw_frames = list(pdftoppm_renderer.renderAllPages(pdfFilename, (w, h)))

        slides = slide.stack_frames(raw_frames)
        pixelCount = sum(s.pixelCount() for s in slides)
        rawCount = len(raw_frames) * numpy.prod(raw_frames[0].shape[:2])
        print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

        print "caching in '%s'..." % cacheFilename
        if os.path.exists(cacheFilename):
            os.unlink(cacheFilename)
        cache.writeSlides(cacheFilename, slides)

    g.setSlides(slides)
    
    if not g.hadEventLoop:
        sys.exit(QtGui.qApp.exec_())
