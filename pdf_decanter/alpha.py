from dynqt import QtGui, qimage2ndarray


def unblend_alpha_1d(rgb, bg, c):
    rgb = numpy.require(rgb, dtype = numpy.int32) * 256
    bg  = numpy.require(bg,  dtype = numpy.int32) * 256
    c   = numpy.require(c,   dtype = numpy.int32) * 256
    alpha = (numpy.sum(numpy.abs(rgb + 128 - bg), 1) * 255 /
             numpy.sum(numpy.abs(c         - bg), 1))
    alpha = alpha.clip(0, 255)
    return alpha


def unblend_alpha(rgb, bg, c):
    rgb, bg = numpy.broadcast_arrays(rgb, bg)
    diff = rgb - bg
    changed_y, changed_x = numpy.nonzero(diff.any(-1))

    rgb_i = rgb[changed_y, changed_x]
    bg_i  = bg [changed_y, changed_x]

    alpha_i = unblend_alpha_1d(rgb_i, bg_i, c)

    alpha = numpy.zeros(bg.shape[:2], numpy.uint8)
    alpha[changed_y, changed_x] = alpha_i
    return alpha


def blend_images(bg, alpha, c):
    _, bg = numpy.broadcast_arrays(alpha[...,None], bg)
    composedImg = qimage2ndarray.array2qimage(bg)

    # build fg image:
    fgImg = QtGui.QImage(composedImg.size(), QtGui.QImage.Format_ARGB32)
    qimage2ndarray.rgb_view(fgImg)[:] = c
    qimage2ndarray.alpha_view(fgImg)[:] = alpha

    # compose:
    p = QtGui.QPainter(composedImg)
    p.drawImage(0, 0, fgImg)
    p.end()

    return qimage2ndarray.rgb_view(composedImg)


def verified_unblend(rgb, bg, c, maxAbsDiff = 1):
    alpha = unblend_alpha(rgb, bg, c)
    composed = blend_images(bg, alpha, c)
    if numpy.all(numpy.abs((composed - rgb).view(numpy.int8)) <= maxAbsDiff):
        return alpha
