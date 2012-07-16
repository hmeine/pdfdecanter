from __future__ import division
import QtPoppler
from PyQt4 import QtGui, QtCore
import qimage2ndarray
import sys

def renderAllPages(pdfFilename, sizePX = None, dpi = None, pageCount = None):
    doc = QtPoppler.Poppler.Document.load(pdfFilename)
    doc.setRenderHint(QtPoppler.Poppler.Document.Antialiasing and QtPoppler.Poppler.Document.TextAntialiasing)

    pageCount = doc.numPages()
    for pageIndex in range(pageCount):
        sys.stdout.write("\rrendering page %d / %d..." % (pageIndex, pageCount))
        sys.stdout.flush()

        page = doc.page(pageIndex)
        if page:
            renderSize = QtCore.QSize(page.pageSize())
            if sizePX:
                widthPX, heightPX = sizePX
                renderSize.scale(widthPX, heightPX, QtCore.Qt.KeepAspectRatio)
            scale = renderSize.width() / page.pageSize().width()
            qImg = page.renderToImage(scale * 72, scale * 72)
            yield qimage2ndarray.rgb_view(qImg)

    print
