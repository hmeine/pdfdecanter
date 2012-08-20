#!/usr/bin/env python
from __future__ import division

from dynqt import QtCore, QtGui, QtOpenGL

import numpy, os, sys, time, tempfile, math, operator
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

w, h = 1024, 768

BLEND_DURATION = 150

PADDING_X = int(w * 0.03)
PADDING_Y = int(h * 0.03)
LINEBREAK_PADDING = int(2.5 * PADDING_Y)
INDENT_X = 0 # w / 8

class GeometryAnimation(QtCore.QVariantAnimation):
    def __init__(self, item, parent = None):
        QtCore.QVariantAnimation.__init__(self, parent)
        self._item = item

    def updateCurrentValue(self, value):
        self._item.setPos(value.topLeft())
        self._item.setScale(value.width())


class PDFDecanter(QtCore.QObject):
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

        if view.scene() is not None:
            self._scene = view.scene()
            self._scene.setSceneRect(0, 0, w, h)
        else:
            self._scene = QtGui.QGraphicsScene(0, 0, w, h)
            self._view.setScene(self._scene)
        self._scene.setBackgroundBrush(QtCore.Qt.black)
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

        self._hideMouseTimer = QtCore.QTimer(self)
        self._hideMouseTimer.setSingleShot(False)
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
        return w, h

    def presentationBounds(self):
        result = QtCore.QRectF()
        for r in self._renderers:
            br = r.boundingRect()
            br.translate(r.pos())
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
        elif obj is self._scene:
            if event.type() == QtCore.QEvent.GraphicsSceneMousePress:
                self.mousePressEvent(event)
            elif event.type() == QtCore.QEvent.GraphicsSceneMouseRelease:
                self.mouseReleaseEvent(event)
        if event.isAccepted():
            return True
        return False

    def resizeEvent(self, e):
        w, h = self.slideSize()
        factor = min(e.size().width() / w,
                     e.size().height() / h)
        self._view.resetMatrix()
        self._view.scale(factor, factor)

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
            if self._currentFrameIndex < self._slides.frameCount() - 1:
                self.gotoFrame(self._currentFrameIndex + 1, animated = True)
        else:
            for item in self._scene.items(e.scenePos()):
                if isinstance(item, slide_renderer.SlideRenderer):
                    slideIndex = self._renderers.index(item)
                    self.gotoFrame(self._slides[slideIndex].currentFrame().frameIndex(), animated = False)
                    break

    def loadPDF(self, pdfFilename, cacheFilename = None):
        slides = None

        if cacheFilename:
            if cacheFilename is True:
                cacheFilename = os.path.join(
                    tempfile.gettempdir(),
                    "pdf_decanter_cache_%s.bz2" % (os.path.abspath(pdfFilename).replace("/", "!"), ))
                sys.stderr.write('ATTENTION! unpickling from system-wide tempdir is a security risk!\n')

            if os.path.exists(cacheFilename):
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

            wallClockTime = time.time()
            cpuTime = time.clock()

            raw_frames = renderer.renderAllPages(pdfFilename, sizePX = self.slideSize(),
                                                 pageCount = infos and infos.pageCount())

            slides = presentation.stack_frames(raw_frames)
            slides.setPDFInfos(infos)

            print "complete rendering took %.3gs. (%.3gs. real time)" % (
                time.clock() - cpuTime, time.time() - wallClockTime)

            if cacheFilename:
                sys.stdout.write("caching in '%s'...\n" % cacheFilename)
                bz2_pickle.pickle(cacheFilename, slides)

        self.setSlides(slides)

    def setSlides(self, slides):
        self._slides = slides
        assert not self._renderers, "FIXME: delete old renderers / graphics items"
        self._renderers = [slide_renderer.SlideRenderer(s, self._presentationItem) for s in slides]
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
                slideLevel[self._slides.frame(frameIndex).slide().slideIndex()] = level

            # prevent too many linebreaks (very fine-grained PDF outline):
            while numpy.diff(numpy.nonzero(slideLevel)[0]).mean() < self._overviewColumnCount-0.5:
                slideLevel[slideLevel == slideLevel.max()] = 0

        x = y = col = 0
        lastLineBreak = 0
        for i, renderer in enumerate(self._renderers):
            if slideLevel[i] and lastLineBreak < i - 1:
                y += (h + PADDING_Y + LINEBREAK_PADDING / slideLevel[i])
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
            # center overview if smaller than scene (evenly distributing black margin):
            if self._scene.sceneRect().height() > self.presentationBounds().height() * scale:
                pos.setY(0.5 * (self._scene.sceneRect().height() - self.presentationBounds().height() * scale))
            else:
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
        return self._scene.sceneRect().width() / self.presentationBounds().width()

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
        slideIndex = self._slides.frame(self._currentFrameIndex).slide().slideIndex()
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
            if not self._inOverview:
                self._presentationItem.setPos(-r2.pos())

    def gotoFrame(self, frameIndex, animated = False):
        self._resetSlideAnimation()

        targetFrame = self._slides.frame(frameIndex)
        renderer = self._renderers[targetFrame.slide().slideIndex()]
        renderer.uncover()
        renderer.showFrame(targetFrame.subIndex())

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
                self._slideAnimation.finished.connect(self._resetSlideAnimation)

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

                self._slideAnimation.addAnimation(slideOutAnim)
                self._slideAnimation.addAnimation(slideInAnim)
                self._slideAnimation.start()

        self._currentFrameIndex = frameIndex

        if not self._inOverview:
            self._presentationItem.setPos(-renderer.pos())
        else:
            self._inOverview = False
            self._animateOverviewGroup(-renderer.pos(), 1.0)

    def _clearGotoSlide(self):
        self._gotoSlideIndex = None

    def followLink(self, link):
        if self._inOverview:
            return False
        if isinstance(link, int):
            frameIndex = link
            self.gotoFrame(frameIndex, animated = True)
            self._mousePressPos = None # don't handle click again in mouseReleaseEvent
            return True
        return False

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
                self.gotoFrame(self._slides[slideIndex].currentFrame().frameIndex(), animated = True)
        elif event.text() == 'Q':
            self._view.window().close()
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
                if self._currentFrameIndex < self._slides.frameCount() - 1:
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
            currentSlideIndex = self._slides.frame(self._currentFrameIndex).slide().slideIndex()
            if event.key() == QtCore.Qt.Key_Right:
                if currentSlideIndex < len(self._slides)-1:
                    desiredSlideIndex = currentSlideIndex + 1
            elif event.key() == QtCore.Qt.Key_Left:
                if currentSlideIndex > 0:
                    desiredSlideIndex = currentSlideIndex - 1

        if desiredSlideIndex is not None:
            self._currentFrameIndex = self._slides[desiredSlideIndex].currentFrame().frameIndex()
            self._updateCursor(animated = True)


def start(view = None):
    global app
    hasApp = QtGui.QApplication.instance()
    if not hasApp:
        import sys
        app = QtGui.QApplication(sys.argv)
    else:
        app = hasApp
    app.setApplicationName("PDF Decanter")
    app.setApplicationVersion(__version__)

    result = PDFDecanter(view)
    result.hadEventLoop = hasattr(app, '_in_event_loop') and app._in_event_loop # IPython support
    return result


if __name__ == "__main__":
    import sys

    from optparse import OptionParser

    op = OptionParser(usage = "%prog [options] <filename.pdf>")
    op.add_option("--no-opengl", action = "store_false",
                  dest = "use_opengl", default = True,
                  help = "disable OpenGL for rendering (default: use OpenGL)")
    op.add_option("--cache", action = "store_true",
                  dest = "use_cache", default = False,
                  help = "use caching in system-wide temp folder")
    options, args = op.parse_args()

    g = start()
    
    g.view().show()
    if sys.platform == "darwin":
        g.view().raise_()

    if options.use_opengl:
        g.enableGL()

    pdfFilename, = args

    if not 'slides' in globals():
        g.loadPDF(pdfFilename, cacheFilename = options.use_cache)

        pixelCount = g._slides.pixelCount()
        ss = g._slides[0].size()
        rawCount = g._slides.frameCount() * ss.width() * ss.height()
        print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

    if not g.hadEventLoop:
        sys.exit(QtGui.qApp.exec_())
