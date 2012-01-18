import subprocess, cStringIO, PIL.Image, numpy

def renderPDFPage(pdfFilename, pageIndex, (widthPX, heightPX)):
    pdftoppm = subprocess.Popen(('pdftoppm -f %(pageIndex)d -l %(pageIndex)d '
                                 '-scale-to-x %(widthPX)d '
                                 '-scale-to-y %(heightPX)d' % locals()).split() +
                                [pdfFilename],
                                 stdout = subprocess.PIPE)
    ppmData, _ = pdftoppm.communicate()
    assert pdftoppm.returncode == 0
    if not ppmData:
        return None # in the future (when we have PDF metadata), could raise error instead

    ppm = cStringIO.StringIO(ppmData)
    img = PIL.Image.open(ppm)
    result = numpy.asanyarray(img)
    return result
