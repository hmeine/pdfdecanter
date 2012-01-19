import subprocess, numpy, string

def renderPDFPage(pdfFilename, pageIndex, (widthPX, heightPX)):
    command = ('pdftoppm -f %(pageIndex)d -l %(pageIndex)d '
               '-scale-to-x %(widthPX)d '
               '-scale-to-y %(heightPX)d' % locals()).split()
    command.append(pdfFilename)

    pdftoppm = subprocess.Popen(command, stdout = subprocess.PIPE)

    result = readPPM(pdftoppm.stdout)

    pdftoppm.wait()
    assert pdftoppm.returncode == 0

    return result

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
    assert header == "P6"
    
    width = int(_readWord())
    height = int(_readWord())
    maxVal = int(_readWord())
    assert maxVal < 65536

    return numpy.fromfile(file,
                          dtype = numpy.uint8 if maxVal < 256 else numpy.uint16,
                          count = width * height * 3).reshape((height, -1, 3))
