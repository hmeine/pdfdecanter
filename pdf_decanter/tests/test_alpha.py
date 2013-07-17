from PyQt4 import QtGui
import qimage2ndarray, numpy, os
from ..alpha import verified_unblend

def imread(filename):
    filename = os.path.join(os.path.dirname(__file__), filename)
    return qimage2ndarray.rgb_view(QtGui.QImage(filename))

def color(r, g, b):
    return numpy.array([r, g, b], numpy.uint8)

# --------------------------------------------------------------------

def test_black_on_white():
    rgb = imread('test_on_white.png')
    bg = color(255, 255, 255)
    c = color(0, 0, 0)
    assert verified_unblend(rgb, bg, c) is not None


def test_white_on_black():
    rgb = imread('test_alpha.png')
    bg = color(0, 0, 0)
    c = color(255, 255, 255)
    assert verified_unblend(rgb, bg, c) is not None


def test_black_on_bg():
    rgb = imread('test_on_bg.png')
    bg = imread('test_bg.png')
    c = color(0, 0, 0)
    assert verified_unblend(rgb, bg, c) is not None


def test_green_on_bg():
    rgb = imread('test_on_bg2.png')
    bg = imread('test_bg.png')
    c = color(181, 255, 64)
    assert verified_unblend(rgb, bg, c) is not None
