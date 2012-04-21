import h5py, numpy
from dynqt import QtCore, array2qimage, rgb_view
import slide

def _writePatches(group, patches):
    for k, (pos, patch) in enumerate(patches):
        ds = group.create_dataset('patch%d' % k, data = rgb_view(patch))
        ds.attrs['pos'] = (pos.x(), pos.y())

def writeSlides(filename, slides):
    with h5py.File(filename) as f:
        f.attrs['format_version'] = slide.Presentation.FORMAT_VERSION

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

def _readPatches(group):
    result = []
    for k in range(len(group)):
        patch = group['patch%d' % k]
        qimg = array2qimage(numpy.asarray(patch))
        x, y = patch.attrs['pos']
        pos = QtCore.QPointF(x, y)
        result.append((pos, qimg))
    return result
        
def readSlides(filename):
    slides = []

    with h5py.File(filename) as f:
        if f.attrs.get('format_version', 1) < slide.Presentation.FORMAT_VERSION:
            return None

        for i in range(len(f)):
            sg = f['slide%d' % i]
            w, h = sg.attrs['size']
            s = slide.Slide(QtCore.QSizeF(w, h))
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

    return slides
