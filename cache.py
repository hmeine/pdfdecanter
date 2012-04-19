import h5py, numpy, qimage2ndarray
from PyQt4 import QtCore
import slide

def _writePatches(group, patches):
    for k, (pos, patch) in enumerate(patches):
        ds = group.create_dataset('patch%d' % k, data = qimage2ndarray.rgb_view(patch))
        ds.attrs['pos'] = (pos.x(), pos.y())

def writeSlides(filename, slides):
    f = h5py.File(filename)

    for i, s in enumerate(slides):
        sg = f.create_group("slide%d" % i)
        sg.attrs['size'] = (s.size().width(), s.size().height())

        g = sg.create_group('header')
        _writePatches(g, s.header())

        g = sg.create_group('footer')
        _writePatches(g, s.footer())

        for j, frame in enumerate(s._frames):
            g = sg.create_group("frame%d" % j)
            _writePatches(g, frame)

    f.close()

def _readPatches(group):
    result = []
    for k in range(len(group)):
        patch = group['patch%d' % k]
        qimg = qimage2ndarray.array2qimage(numpy.asarray(patch))
        x, y = patch.attrs['pos']
        pos = QtCore.QPointF(x, y)
        result.append((pos, qimg))
    return result
        
def readSlides(filename):
    slides = []

    f = h5py.File(filename)

    for i in range(len(f)):
        sg = f['slide%d' % i]
        w, h = sg.attrs['size']
        s = slide.Slide(QtCore.QSize(w, h))
        s._header = _readPatches(sg['header'])
        s._footer = _readPatches(sg['footer'])
        for j in range(len(sg)):
            try:
                fg = sg['frame%d' % j]
            except KeyError:
                pass
            else:
                s._frames.append(_readPatches(fg))
        slides.append(s)

    f.close()

    return slides
