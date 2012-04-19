import numpy

def array2qimage_pure_python(arr):
	assert numpy.ndim(arr) == 3 and arr.shape[2] == 3
	h, w = arr.shape[:2]
	aligned = numpy.zeros((h, w, 4), numpy.uint8)
	aligned[:,:,2::-1] = arr
	result = QtGui.QImage(aligned.data, w, h, QtGui.QImage.Format_RGB32)
	return result.copy()

if True:
	import sip
	sip.setapi("QString", 2)
	from PyQt4 import QtCore, QtGui, QtOpenGL

	from qimage2ndarray import array2qimage, rgb_view
else:
	#	from PySide import QtCore, QtGui, QtOpenGL
	from PythonQt import QtCore, QtGui, QtOpenGL

	array2qimage = array2qimage_pure_python

	rgb_view = NotImplemented
