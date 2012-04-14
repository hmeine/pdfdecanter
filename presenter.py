from PyQt4 import QtCore, QtGui
import qimage2ndarray
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

        self.setFrameStyle(QtGui.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self._scene = QtGui.QGraphicsScene(0, 0, w, h)
        self.setScene(self._scene)

    # def resizeEvent(self, e):
    #     self.fitInView(0, 0, w, h, QtCore.Qt.KeepAspectRatio)
    #     return QtGui.QGraphicsView.resizeEvent(self, e)



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


def addSlide(slide):
    rect = QtCore.QRect(QtCore.QPoint(0, 0), slide.size())
    result = QtGui.QGraphicsRectItem(QtCore.QRectF(rect))
    result.setBrush(QtCore.Qt.white)
    pms = []
    pmis = []
    for r, patch in slide._frames[0]:
        pixmap = QtGui.QPixmap.fromImage(patch)
        pms.append(pms)
        pmItem = QtGui.QGraphicsPixmapItem(result)
        pmItem.setPos(QtCore.QPointF(r.topLeft()))
        pmis.append(pmItem)

    g._scene.addItem(result)
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
        pdfFilename = '../testtalks/defense.pdf'
        slides = list(pdftoppm_renderer.renderAllPages(pdfFilename, (w, h)))

        comp = slide.stack_frames(slides)
        print sum(s.pixelCount() for s in comp)
    
    pms = [addSlide(s) for s in comp]

    cols = 5
    rows = (len(comp) + cols - 1) / cols
    marginX = 20
    marginY = 20
    g._scene.setSceneRect(0, 0,
                          cols * (w + marginX) - marginX,
                          rows * (h + marginY) - marginY)
    g._scene.setBackgroundBrush(QtCore.Qt.black)

    for i, pm in enumerate(pms):
        pm.setPos((w + marginX) * (i % cols), (h + marginY) * (i / cols))

    # overview_factor = float(w) / g._scene.sceneRect().width()
    # g.scale(overview_factor, overview_factor)

    if not g.hadEventLoop:
        sys.exit(QtGui.qApp.exec_())
