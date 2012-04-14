import subprocess, numpy, string

def startRenderer(pdfFilename, pageIndex, sizePX):
    widthPX, heightPX = sizePX
    command = ('pdftoppm '
               '-scale-to-x %(widthPX)d '
               '-scale-to-y %(heightPX)d' % locals()).split()
    if pageIndex:
        command.extend(('-f %(pageIndex)d -l %(pageIndex)d' % locals()).split())
    command.append(pdfFilename)

    result = subprocess.Popen(command, stdout = subprocess.PIPE)

    return result

def renderPDFPage(pdfFilename, pageIndex, sizePX):
    print "rendering page %d..." % pageIndex

    pdftoppm = startRenderer(pdfFilename, pageIndex, sizePX)

    result = readPPM(pdftoppm.stdout)

    rest, _ = pdftoppm.communicate()
    assert not rest, "pdftoppm returned more than the expected PPM data (%d extra bytes)" % len(rest)
    assert pdftoppm.returncode == 0

    return result

def renderAllPages(pdfFilename, sizePX):
    pdftoppm = startRenderer(pdfFilename, None, sizePX)

    pageIndex = 1
    while True:
        print "rendering page %d..." % pageIndex

        try:
            page = readPPM(pdftoppm.stdout)
        except IOError, e:
            if e.errno == 4:
                break
        if page is None:
            break
        
        yield page
        pageIndex += 1

    rest, _ = pdftoppm.communicate()
    assert not rest, "pdftoppm returned more than the expected PPM data (%d extra bytes)" % len(rest)
    assert pdftoppm.returncode == 0

def readPPM(file):
    def _readWord(prefix = ""):
        result = prefix
        while True:
            ch = file.read(1)
            if not ch:
                return None
            elif ch in string.whitespace:
                if result:
                    break
                continue
            elif ch == '#':
                file.readline()
            result += ch
        return result

    header = _readWord()
    if header is None:
        return None
    assert header == "P6"
    
    width = int(_readWord())
    height = int(_readWord())
    maxVal = int(_readWord())
    assert maxVal < 65536

    pixelData = numpy.fromfile(
        file,
        dtype = numpy.uint8 if maxVal < 256 else numpy.uint16,
        count = width * height * 3)
    return pixelData.reshape((height, -1, 3))
