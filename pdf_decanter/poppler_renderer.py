from __future__ import division
try:
    import popplerqt4 as QtPoppler
except ImportError:
    import QtPoppler
from PyQt4 import QtCore
import qimage2ndarray
import sys

class PopplerRenderer(object):
    def __init__(self, pdfFilename, sizePX = None, dpi = None, pageCount = None):
        self._doc = QtPoppler.Poppler.Document.load(pdfFilename)
        self._doc.setRenderHint(QtPoppler.Poppler.Document.Antialiasing |
                                QtPoppler.Poppler.Document.TextAntialiasing)

        self._sizePX = sizePX
        self._dpi = dpi

        self._pageIndex = 0

    def __iter__(self):
        return self

    def next(self):
        pageCount = self._doc.numPages()

        if self._pageIndex >= pageCount:
            raise StopIteration
        
        sys.stdout.write("\rrendering page %d / %d..." % (self._pageIndex + 1, pageCount))
        sys.stdout.flush()

        page = self._doc.page(self._pageIndex)
        assert page

        renderSize = QtCore.QSize(page.pageSize())
        if self._sizePX:
            widthPX, heightPX = self._sizePX
            renderSize.scale(widthPX, heightPX, QtCore.Qt.KeepAspectRatio)
        scale = renderSize.width() / page.pageSize().width()
        qImg = page.renderToImage(scale * 72, scale * 72)
        result = qimage2ndarray.rgb_view(qImg)

        self._pageIndex += 1
        if self._pageIndex == pageCount:
            print

        return result

renderAllPages = PopplerRenderer
