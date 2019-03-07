from ..pdf_infos import PDFInfos
from ..pdf_renderer import renderAllPages
from ..decomposer import decompose_pages

pdfFilename = "../testtalks/FATE_Motivation.pdf"
sizePX = (1024, 768)

infos = PDFInfos.create(pdfFilename)

pages = list(renderAllPages(pdfFilename, sizePX = sizePX,
                            pageCount = infos and infos.pageCount()))
    
slides = decompose_pages(pages, infos)

def test_frame_sizes():
    for frame in slides.frames():
        assert frame.sizeF().width() == sizePX[0]
        assert frame.sizeF().height() == sizePX[1]

def test_frame_count():
    assert slides.frameCount() == infos.pageCount()
    assert len(list(slides.frames())) == slides.frameCount()

def test_pdfInfos():
    assert slides.pdfInfos() is infos

# --------------------------------------------------------------------
    
from ..slide_renderer import FrameRenderer

import numpy
from ..dynqt import QtGui, qimage2ndarray

hasApp = QtGui.QApplication.instance()
if not hasApp:
    app = QtGui.QApplication([])


def get_render_result(renderer):
    frame = renderer.frame()
    img = QtGui.QImage(frame.sizeF().toSize(), QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor(0, 0, 0).rgb())
    p = QtGui.QPainter(img)
    r = renderer.sceneBoundingRect()
    p.translate(-r.topLeft())
    renderer.scene().render(p, r)
    return qimage2ndarray.rgb_view(img)


def assert_render_result(renderer, expected_result):
    actual_result = get_render_result(renderer)
    assert actual_result.shape == expected_result.shape
    rendering_differences = (actual_result - expected_result).view(numpy.int8)
    assert rendering_differences.max() <= 2
    assert rendering_differences.min() >= 0


import pytest

@pytest.fixture(params = list(range(len(pages))))
def frame_index(request):
    return request.param


def test_render_results(frame_index):
    renderer = FrameRenderer(None)
    scene = QtGui.QGraphicsScene(0, 0, sizePX[0], sizePX[1])
    scene.addItem(renderer)
    renderer.setFrame(slides.frame(frame_index))
    assert_render_result(renderer, pages[frame_index])
