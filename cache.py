import h5py, numpy, qimage2ndarray
from PyQt4 import QtCore
import slide

def writeSlides(filename, slides):
    f = h5py.File(filename)

    for i, s in enumerate(slides):
        sg = f.create_group("slide%d" % i)
        sg.attrs['size'] = (s.size().width(), s.size().height())
        for j, frame in enumerate(s._frames):
            fg = sg.create_group("frame%d" % j)
            for k, (pos, patch) in enumerate(frame):
                ds = fg.create_dataset('patch%d' % k, data = qimage2ndarray.rgb_view(patch))
                ds.attrs['pos'] = (pos.x(), pos.y())

    f.close()

def readSlides(filename):
    slides = []

    f = h5py.File(filename)

    for i in range(len(f)):
        sg = f['slide%d' % i]
        w, h = sg.attrs['size']
        s = slide.Slide(QtCore.QSize(w, h))
        for j in range(len(sg)):
            fg = sg['frame%d' % j]
            frame = []
            for k in range(len(fg)):
                patch = fg['patch%d' % k]
                qimg = qimage2ndarray.array2qimage(numpy.asarray(patch))
                x, y = patch.attrs['pos']
                pos = QtCore.QPointF(x, y)
                frame.append((pos, qimg))
            s._frames.append(frame)
        slides.append(s)

    f.close()

    return slides
