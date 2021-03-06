import subprocess, numpy, string, sys

def startRenderer(pdfFilename, pageIndex, sizePX = None, dpi = None):
    command = ['pdftoppm']
    if sizePX is not None:
        widthPX, heightPX = sizePX
        command.extend(['-scale-to-x', str(widthPX),
                        '-scale-to-y', str(heightPX)])
    elif dpi is not None:
        command.extend(['-r', str(dpi)])
    if pageIndex is not None:
        command.extend(('-f %(pageIndex)d -l %(pageIndex)d' % locals()).split())
    command.append(pdfFilename)

    result = subprocess.Popen(command, stdout = subprocess.PIPE)

    return result

def renderPDFPage(pdfFilename, pageIndex, **kwargs):
    #print "rendering page %d..." % pageIndex

    pdftoppm = startRenderer(pdfFilename, pageIndex, **kwargs)

    result = readPPM(pdftoppm.stdout)

    rest, _ = pdftoppm.communicate()
    assert not rest, "pdftoppm returned more than the expected PPM data (%d extra bytes)" % len(rest)
    assert pdftoppm.returncode == 0

    return result

def renderAllPages(pdfFilename, **kwargs):
    pageCount = None
    if 'pageCount' in kwargs:
        pageCount = kwargs['pageCount']
        kwargs = dict(kwargs)
        del kwargs['pageCount']
    
    pdftoppm = startRenderer(pdfFilename, None, **kwargs)

    pageIndex = 1
    while pageCount is None or pageIndex <= pageCount:
        sys.stdout.write("\rrendering page %d%s..." % (pageIndex, " / %d" % pageCount if pageCount is not None else ""))
        sys.stdout.flush()

        try:
            page = readPPM(pdftoppm.stdout)
        except IOError as e:
            if e.errno == 4:
                break
        if page is None:
            break
        
        yield page
        pageIndex += 1

    print()
    rest, _ = pdftoppm.communicate()
    assert not rest, "pdftoppm returned more than the expected PPM data (%d extra bytes)" % len(rest)
    assert pdftoppm.returncode == 0

def readPPM(file_handle):
    def _readWord(prefix = b''):
        result = prefix
        while True:
            ch = file_handle.read(1)
            if not ch:
                return None
            elif ch in b' \t\n\r\x0b\x0c':
                if result:
                    break
                continue
            elif ch == b'#':
                file_handle.readline()
            result += ch
        return result

    header = _readWord()
    if header is None:
        return None
    assert header == b'P6'
    
    width = int(_readWord())
    height = int(_readWord())
    maxVal = int(_readWord())
    assert maxVal < 65536

    dtype = numpy.dtype(
        numpy.uint8 if maxVal < 256 else numpy.uint16)
    
    pixelData = numpy.frombuffer(
        file_handle.read(width * height * 3 * dtype.itemsize),
        dtype = dtype)
    return pixelData.reshape((height, -1, 3))
