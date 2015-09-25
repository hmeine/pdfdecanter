#!/usr/bin/env python
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

import sys, re
import pdf_decanter

from optparse import OptionParser

op = OptionParser(usage = "%prog [options] <filename.pdf>")
op.add_option("--no-opengl", action = "store_false",
              dest = "use_opengl", default = True,
              help = "disable OpenGL for rendering (default: use OpenGL)")
op.add_option("--size", "-s", default = '1024x768',
              help = "set target rendering / window size in pixels")
op.add_option("--cache", action = "store_true",
              dest = "create_cache", default = False,
              help = "use caching, create new cache if necessary (default: use if present, but don't create cache file)")
op.add_option("--ignore-cache", action = "store_false",
              dest = "use_cache", default = None,
              help = "ignore cache file (even if it seems to be up-to-date)")
op.add_option("--no-gui", action = "store_false",
              dest = "show_gui", default = True,
              help = "skip main GUI (use for benchmarking / cache generation)")
op.add_option("--profile", action = "store_true",
              help = "enable profiling (and dump to 'pdf_decanter.prof')")
options, args = op.parse_args()

pdfFilename, = args

ma = re.match('([0-9]+)[ x*,/]([0-9]+)', options.size)
if not ma:
    sys.stderr.write('ERROR: Could not parse size argument %r; expected format like 1024x768\n')
    sys.exit(1)
slideSize = map(int, ma.groups())

g = pdf_decanter.start(show = options.show_gui, slideSize = slideSize)

if options.use_opengl and options.show_gui:
    g.enableGL()

if options.profile:
    import cProfile
    pr = cProfile.Profile()
    pr.enable()

g.loadPDF(pdfFilename,
          useCache = options.use_cache,
          createCache = options.create_cache)

if options.profile:
    pr.disable()
    pr.dump_stats('pdf_decanter.prof')

pixelCount = g._slides.pixelCount()
sw, sh = g.slideSize() # _slides[0].sizeF()
rawCount = g._slides.frameCount() * sw * sh
print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

if options.show_gui and not g.hadEventLoop:
    from pdf_decanter.dynqt import QtGui
    sys.exit(QtGui.qApp.exec_())
