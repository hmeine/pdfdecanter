#!/usr/bin/env python
import sys
import pdf_decanter

from optparse import OptionParser

op = OptionParser(usage = "%prog [options] <filename.pdf>")
op.add_option("--no-opengl", action = "store_false",
              dest = "use_opengl", default = True,
              help = "disable OpenGL for rendering (default: use OpenGL)")
op.add_option("--cache", action = "store_true",
              dest = "create_cache", default = False,
              help = "use caching, create new cache if necessary (default: use if present, but don't create cache file)")
op.add_option("--ignore-cache", action = "store_false",
              dest = "use_cache", default = None,
              help = "ignore cache file (even if it seems to be up-to-date)")
options, args = op.parse_args()

pdfFilename, = args

g = pdf_decanter.start()

if options.use_opengl:
    g.enableGL()

g.loadPDF(pdfFilename,
          useCache = options.use_cache,
          createCache = options.create_cache)

pixelCount = g._slides.pixelCount()
ss = g._slides[0].size()
rawCount = g._slides.frameCount() * ss.width() * ss.height()
print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

if not g.hadEventLoop:
    from pdf_decanter.dynqt import QtGui
    sys.exit(QtGui.qApp.exec_())
