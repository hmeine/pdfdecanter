from PyQt4 import QtCore, QtGui
import numpy
import pdftoppm_renderer, slide

__version__ = "0.1"

# from ui_presenter import Ui_PDFPresenter

# class PDFPresenter(QtGui.QMainWindow):
#     def __init__(self):
#         QtGui.QMainWindow.__init__(self)
#         self._ui = Ui_PDFPresenter()
#         self._ui.setupUi(self)

w, h = 640, 480


class PDFPresenter(QtGui.QGraphicsView):
    def __init__(self):
        QtGui.QGraphicsView.__init__(self)
        self.resize(w, h)

        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

        self.setFrameStyle(QtGui.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self._scene = QtGui.QGraphicsScene(0, 0, w, h)
        self._scene.setBackgroundBrush(QtCore.Qt.black)
        self.setScene(self._scene)

        self._slideViewport = QtGui.QGraphicsRectItem(QtCore.QRectF(0, 0, w, h))
        self._scene.addItem(self._slideViewport)
        self._slideViewport.setFlag(QtGui.QGraphicsItem.ItemClipsChildrenToShape)

        self._group = QtGui.QGraphicsItemGroup(self._slideViewport)

        self._renderers = None
        self._currentFrameIndex = 0

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
        self._renderers = [slide.SlideRenderer(s, self._group) for s in slides]
        self._setupGrid()

        self._frameSlide = []
        for i, s in enumerate(slides):
            self._frameSlide.extend([(i, j) for j in range(len(s))])

    def _setupGrid(self):
        cols = 5
        rows = (len(slides) + cols - 1) / cols
        marginX = 20
        marginY = 20
        # self._scene.setSceneRect(0, 0,
        #     cols * (w + marginX) - marginX,
        #     rows * (h + marginY) - marginY)

        for i, renderer in enumerate(self._renderers):
            pm = renderer.slideItem()
            pm.setPos((w + marginX) * (i % cols), (h + marginY) * (i / cols))

    def showOverview(self):
        self._setupGrid()
        overview_factor = float(self.width()) / self._scene.sceneRect().width()
        self.scale(overview_factor, overview_factor)

        # cursor = self._scene.addRect(renderers[11].slideItem().sceneBoundingRect())
        # cursor.setPen(QtGui.QPen(QtCore.Qt.yellow, 25))
        # cursor.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0, 100)))

    def gotoFrame(self, frameIndex):
        slideIndex, subFrame = self._frameSlide[frameIndex]
        slide = self._slides[slideIndex]
        renderer = self._renderers[slideIndex]
        slidePos = renderer.slideItem().pos()
        self._group.setPos(-slidePos)
        # self.resetTransform()
        # self.horizontalScrollBar().setValue(slidePos.x())
        # self.verticalScrollBar().setValue(slidePos.y())
        renderer.showFrame(subFrame)
        self._currentFrameIndex = frameIndex

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown):
            if self._currentFrameIndex < len(self._frameSlide) - 1:
                self.gotoFrame(self._currentFrameIndex + 1)
        elif event.key() in (QtCore.Qt.Key_Backspace, QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp):
            if self._currentFrameIndex > 0:
                self.gotoFrame(self._currentFrameIndex - 1)
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

    if not 'raw_frames' in globals():
        pdfFilename = '../testtalks/defense.pdf'
        #        pdfFilename = '../testtalks/infiltrate12-thestackisback.pdf'
        raw_frames = list(pdftoppm_renderer.renderAllPages(pdfFilename, (w, h)))

    if not 'slides' in globals():
        slides = slide.stack_frames(raw_frames)
        pixelCount = sum(s.pixelCount() for s in slides)
        rawCount = len(raw_frames) * numpy.prod(raw_frames[0].shape[:2])
        print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

    g.setSlides(slides)
    
    if not g.hadEventLoop:
        sys.exit(QtGui.qApp.exec_())
