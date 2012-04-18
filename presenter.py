from PyQt4 import QtCore, QtGui, QtOpenGL
import numpy, os
import pdftoppm_renderer, slide, cache

__version__ = "0.1"

# from ui_presenter import Ui_PDFPresenter

# class PDFPresenter(QtGui.QMainWindow):
#     def __init__(self):
#         QtGui.QMainWindow.__init__(self)
#         self._ui = Ui_PDFPresenter()
#         self._ui.setupUi(self)

w, h = 1024, 768

OVERVIEW_COLS = 5
MARGIN_X = 30
MARGIN_Y = 24
BLEND_DURATION = 150
USE_GL = True

class PDFPresenter(QtGui.QGraphicsView):
    def __init__(self):
        QtGui.QGraphicsView.__init__(self)
        self.resize(w, h)

        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

        self.setFrameStyle(QtGui.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        if USE_GL:
            from OpenGL import GL
            self.setViewport(QtOpenGL.QGLWidget(QtOpenGL.QGLFormat(QtOpenGL.QGL.SampleBuffers)))
            self.setViewportUpdateMode(QtGui.QGraphicsView.FullViewportUpdate)

        self._scene = QtGui.QGraphicsScene(0, 0, w, h)
        self._scene.setBackgroundBrush(QtCore.Qt.black)
        self.setScene(self._scene)

        self._slideViewport = QtGui.QGraphicsRectItem(QtCore.QRectF(0, 0, w, h))
        self._scene.addItem(self._slideViewport)
        self._slideViewport.setFlag(QtGui.QGraphicsItem.ItemClipsChildrenToShape)

        self._group = QtGui.QGraphicsItemGroup(self._slideViewport)

        self._cursor = self._scene.addRect(self._scene.sceneRect())
        self._cursor.setPen(QtGui.QPen(QtCore.Qt.yellow, 25))
        self._cursor.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0, 100)))
        self._cursor.setParentItem(self._group)

        self._renderers = None
        self._currentFrameIndex = None
        self._slideAnimation = None

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
        r = QtCore.QRectF(self._currentSlideItem().boundingRect())
        r.moveTo(self._currentSlideItem().pos())

        if not animated:
            self._cursor.setRect(r)
        else:
            self._cursorAnimation = QtCore.QPropertyAnimation(self, "cursorRect")
            self._cursorAnimation.setDuration(100)
            self._cursorAnimation.setStartValue(self._cursorRect())
            self._cursorAnimation.setEndValue(r)
            self._cursorAnimation.start()
            
            if not self._scene.sceneRect().contains(r.center() * self._groupScale() + self._groupPos()):
                self._animateOverviewGroup(self._overviewPosForCursor(r), self._groupScale())

    def _groupPos(self):
        return self._group.pos()

    def _setGroupPos(self, t):
        self._group.setPos(t)

    groupPos = QtCore.pyqtProperty(QtCore.QPointF, _groupPos, _setGroupPos)

    def _groupScale(self):
        return self._group.transform().m11()

    def _setGroupScale(self, scale):
        transform = QtGui.QTransform.fromScale(scale, scale)
        self._group.setTransform(transform)

    groupScale = QtCore.pyqtProperty(float, _groupScale, _setGroupScale)

    def _animateOverviewGroup(self, pos, scale):
        if pos.y() > 0.0:
            pos.setY(0.0)
        else:
            minY = self._scene.sceneRect().height() - self._group.boundingRect().height() * scale
            if pos.y() < minY:
                pos.setY(minY)

        # FIXME: clear up / reuse QObject:
        self._overviewAnimation = QtCore.QParallelAnimationGroup()

        posAnim = QtCore.QPropertyAnimation(self, "groupPos", self._overviewAnimation)
        posAnim.setDuration(200)
        posAnim.setStartValue(self._groupPos())
        posAnim.setEndValue(pos)

        scaleAnim = QtCore.QPropertyAnimation(self, "groupScale", self._overviewAnimation)
        scaleAnim.setDuration(200)
        scaleAnim.setStartValue(self._groupScale())
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
        self._resetOffsets()

        self._updateCursor(animated = False)

        self._animateOverviewGroup(self._overviewPosForCursor(), self._overviewScale())

        self._inOverview = True

    def _currentRenderer(self):
        slideIndex, _ = self._frame2Slide[self._currentFrameIndex]
        return self._renderers[slideIndex]

    def _currentSlideItem(self):
        return self._currentRenderer().slideItem()

    def _resetOffsets(self):
        """clean up previously offset items"""
        if self._slideAnimation is not None:
            self._slideAnimation = None
            r1, r2 = self._animatedRenderers
            r1.contentOffset = QtCore.QPointF(0, 0)
            r2.setTemporaryOffset(QtCore.QPointF(0, 0))

    def gotoFrame(self, frameIndex, animated = False):
        self._resetOffsets()

        slideIndex, subFrame = self._frame2Slide[frameIndex]
        renderer = self._renderers[slideIndex]
        renderer.uncover()
        slideItem = renderer.showFrame(subFrame)
        slidePos = slideItem.pos()

        if animated:
            previousRenderer = self._currentRenderer()

            if previousRenderer is not renderer:
                renderer.setTemporaryOffset(
                    previousRenderer.slideItem().pos() - slideItem.pos())
                slidePos = previousRenderer.slideItem().pos()

                self._slideAnimation = QtCore.QParallelAnimationGroup()
                self._animatedRenderers = (previousRenderer, renderer)

                offset = w if frameIndex > self._currentFrameIndex else -w

                slideOutAnim = QtCore.QPropertyAnimation(previousRenderer, "contentOffset", self._slideAnimation)
                slideOutAnim.setDuration(250)
                slideOutAnim.setStartValue(QtCore.QPoint(0, 0))
                slideOutAnim.setEndValue(QtCore.QPoint(-offset, 0))

                slideInAnim = QtCore.QPropertyAnimation(renderer, "contentOffset", self._slideAnimation)
                slideInAnim.setDuration(250)
                slideInAnim.setStartValue(QtCore.QPoint(offset, 0))
                slideInAnim.setEndValue(QtCore.QPoint(0, 0))

                blendAnimation = QtCore.QPropertyAnimation(renderer, "navOpacity", self._slideAnimation)
                blendAnimation.setDuration(BLEND_DURATION)
                blendAnimation.setStartValue(0.0)
                blendAnimation.setEndValue(1.0)
                blendAnimation.start()

                self._slideAnimation.addAnimation(slideOutAnim)
                self._slideAnimation.addAnimation(slideInAnim)
                self._slideAnimation.start()
            else:
                self._blendAnimation = QtCore.QPropertyAnimation(renderer, "frameOpacity")
                self._blendAnimation.setDuration(BLEND_DURATION)
                self._blendAnimation.setStartValue(0.0)
                self._blendAnimation.setEndValue(1.0)
                self._blendAnimation.start()

        self._currentFrameIndex = frameIndex

        if not self._inOverview:
            self._group.setPos(-slidePos)
        else:
            self._inOverview = False
            self._animateOverviewGroup(-slidePos, 1.0)

    def keyPressEvent(self, event):
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
            elif event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Return):
                self.gotoFrame(self._currentFrameIndex)
            elif event.key() in (QtCore.Qt.Key_F, QtCore.Qt.Key_L):
                r = self._currentRenderer()
                r.showFrame(0 if event.key() == QtCore.Qt.Key_F else len(r.slide()) - 1)
            else:
                QtGui.QGraphicsView.keyPressEvent(self, event)
            return

        if event.key() in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown):
            if self._currentFrameIndex < len(self._frame2Slide) - 1:
                self.gotoFrame(self._currentFrameIndex + 1, animated = True)
        elif event.key() in (QtCore.Qt.Key_Backspace, QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp):
            if self._currentFrameIndex > 0:
                self.gotoFrame(self._currentFrameIndex - 1)
        elif event.key() in (QtCore.Qt.Key_Home, ):
            self.gotoFrame(0)
        elif event.key() in (QtCore.Qt.Key_Tab, ):
            self.showOverview()
        # elif event.key() in (QtCore.Qt.Key_P, ):
        #     self._currentRenderer().toggleHeaderAndFooter()
        else:
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

    if not 'slides' in globals():
        if os.path.exists('cache.h5'):
            slides = cache.readSlides('cache.h5')
        else:
            if not 'raw_frames' in globals():
                raw_frames = []
                for pdfFilename in (args or ('../testtalks/defense.pdf', )):
                    raw_frames.extend(pdftoppm_renderer.renderAllPages(pdfFilename, (w, h)))

            slides = slide.stack_frames(raw_frames)
            pixelCount = sum(s.pixelCount() for s in slides)
            rawCount = len(raw_frames) * numpy.prod(raw_frames[0].shape[:2])
            print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

    g.setSlides(slides)
    
    if not g.hadEventLoop:
        sys.exit(QtGui.qApp.exec_())
