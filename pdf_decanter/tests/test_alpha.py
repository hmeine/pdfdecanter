from PyQt5 import QtGui
import qimage2ndarray, numpy, os
from ..alpha import verified_unblend

def imread(filename):
    filename = os.path.join(os.path.dirname(__file__), filename)
    return qimage2ndarray.rgb_view(QtGui.QImage(filename))

def color(r, g, b):
    return numpy.array([r, g, b], numpy.uint8)

# --------------------------------------------------------------------

def _check_alpha(alpha, max_neg_diff = 0, max_pos_diff = 0):
    assert alpha is not None
    assert alpha.dtype == numpy.uint8
    expected_alpha = 255 - imread('test_on_white.png')[...,0]
    diff = (alpha - expected_alpha).view(numpy.int8)
    assert diff.min() >= max_neg_diff
    assert diff.max() <= max_pos_diff


def test_black_on_white():
    rgb = imread('test_on_white.png')
    bg = color(255, 255, 255)
    c = color(0, 0, 0)
    alpha = verified_unblend(rgb, bg, c)
    _check_alpha(alpha, -1)


def test_white_on_black():
    rgb = imread('test_alpha.png')
    bg = color(0, 0, 0)
    c = color(255, 255, 255)
    alpha = verified_unblend(rgb, bg, c)
    _check_alpha(alpha)


def test_black_on_bg():
    rgb = imread('test_on_bg.png')
    bg = imread('test_bg.png')
    c = color(0, 0, 0)
    alpha = verified_unblend(rgb, bg, c)
    _check_alpha(alpha, -4, 1)


def test_green_on_bg():
    rgb = imread('test_on_bg2.png')
    bg = imread('test_bg.png')
    c = color(181, 255, 64)
    alpha = verified_unblend(rgb, bg, c)
    _check_alpha(alpha, -1)
