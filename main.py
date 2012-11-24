#!/usr/bin/env python
import sys
import pdf_decanter

from optparse import OptionParser

op = OptionParser(usage = "%prog [options] <filename.pdf>")
op.add_option("--no-opengl", action = "store_false",
              dest = "use_opengl", default = True,
              help = "disable OpenGL for rendering (default: use OpenGL)")
op.add_option("--cache", action = "store_true",
              dest = "use_cache", default = False,
              help = "use caching in system-wide temp folder")
options, args = op.parse_args()

pdfFilename, = args

g = pdf_decanter.start()

if options.use_opengl:
    g.enableGL()

g.loadPDF(pdfFilename, cacheFilename = options.use_cache)

pixelCount = g._slides.pixelCount()
ss = g._slides[0].size()
rawCount = g._slides.frameCount() * ss.width() * ss.height()
print "%d pixels out of %d retained. (%.1f%%)" % (pixelCount, rawCount, 100.0 * pixelCount / rawCount)

if not g.hadEventLoop:
    from pdf_decanter.dynqt import QtGui
    sys.exit(QtGui.qApp.exec_())
