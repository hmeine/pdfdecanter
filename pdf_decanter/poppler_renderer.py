#  Copyright 2012-2014 Hans Meine <hans_meine@gmx.net>
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.


import popplerqt5 as QtPoppler
from PyQt5 import QtCore
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

    def __next__(self):
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
            print()

        return result

renderAllPages = PopplerRenderer
