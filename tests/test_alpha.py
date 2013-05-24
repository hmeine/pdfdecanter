from PyQt4 import QtCore, QtGui
from PyQt4.QtCore import QSize
from PyQt4.QtGui import QImage, QPainter
import qimage2ndarray, numpy

def imread(filename):
    return qimage2ndarray.rgb_view(QtGui.QImage(filename))

def color(r, g, b):
    return numpy.array([r, g, b])

def unblend_alpha(rgb, bg, c):
    rgb, bg = numpy.broadcast_arrays(rgb, bg)
    diff = rgb - bg
    changed_y, changed_x = numpy.nonzero(diff.any(-1))

    rgb_i = rgb[changed_y, changed_x].T.astype(numpy.float64)
    bg_i = bg[changed_y, changed_x].T.astype(numpy.float64)
    diff_i = rgb_i - bg_i

    alpha_i = (numpy.sum(numpy.abs(rgb_i + 0.5 - bg_i), 0)) / numpy.sum(numpy.abs(c[:,None] - bg_i), 0)
    alpha_i *= 255
    #alpha_i = numpy.round(alpha_i).clip(0, 255)
    #alpha_i = numpy.ceil(alpha_i).clip(0, 255)
    alpha_i = numpy.floor(alpha_i).clip(0, 255)

    alpha = numpy.zeros(bg.shape[:2])
    alpha[changed_y, changed_x] = alpha_i
    return alpha


def blend_images(bg, alpha, c):
    _, bg = numpy.broadcast_arrays(alpha[...,None], bg)
    composedImg = qimage2ndarray.array2qimage(bg)

    # build fg image:
    fgImg = QImage(composedImg.size(), QImage.Format_ARGB32)
    qimage2ndarray.rgb_view(fgImg)[:] = c
    qimage2ndarray.alpha_view(fgImg)[:] = alpha

    # compose:
    p = QPainter(composedImg)
    p.drawImage(0, 0, fgImg)
    p.end()

    return qimage2ndarray.rgb_view(composedImg)


def verified_unblend(rgb, bg, c, maxAbsDiff = 1):
    alpha = unblend_alpha(rgb, bg, c)
    composed = blend_images(bg, alpha, c)
    if numpy.all(numpy.abs((composed - rgb).view(numpy.int8)) <= maxAbsDiff):
        return alpha


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
