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

import numpy
from dynqt import QtGui, qimage2ndarray


def unblend_alpha_1d(rgb, bg, c):
    """Given an Nx3 `rgb` array, a compatible background `bg`
    (e.g. Nx3 or just a 3-tuple with a fixed bg color), and a
    foreground color, return alpha array."""
    
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
    diff *= (c - bg)
    if not diff.any():
        return None
    changed_y, changed_x = numpy.nonzero(diff.any(-1))

    rgb_i = rgb[changed_y, changed_x]
    bg_i  = bg [changed_y, changed_x]

    alpha_i = unblend_alpha_1d(rgb_i, bg_i, c)

    alpha = numpy.zeros(bg.shape[:2], numpy.uint8)
    alpha[changed_y, changed_x] = alpha_i
    return alpha


def blend_images(bg, alpha, c):
    result = numpy.zeros(alpha.shape + (3, ), numpy.uint8)

    bg = numpy.require(bg, dtype = numpy.uint16) * (255 - alpha)[...,None]
    fg = numpy.require(c,  dtype = numpy.uint16) * alpha[...,None]
    return ((bg + fg) / 255).astype(numpy.uint8)


def verified_unblend(rgb, bg, c, maxAbsDiff = 1):
    alpha = unblend_alpha(rgb, bg, c)
    if alpha is None:
        return None
    composed = blend_images(bg, alpha, c)
    diff = (composed - rgb).view(numpy.int8)
    if numpy.all(numpy.abs(diff) <= maxAbsDiff):
        return alpha
    return None
