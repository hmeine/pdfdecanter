import sys, os

class QtDriver(object):
	DRIVERS = ('PyQt4', 'PySide', 'PythonQt')
	
	@classmethod
	def detect_qt(cls):
		for drv in cls.DRIVERS:
			if drv in sys.modules:
				return drv
		return None

	def name(self):
		return self._drv

	def __init__(self, drv = os.environ.get('QT_DRIVER')):
		if drv is None:
			drv = self.detect_qt()
		if drv is None:
			drv = 'PyQt4' # default to PyQt4
		assert drv in self.DRIVERS
		self._drv = drv

	@staticmethod
	def _initPyQt4():
		"""initialize PyQt4 to be compatible with PySide"""
		import sip
		if 'PyQt4.QtCore' in sys.modules:
			# too late to configure API, let's check that it was properly parameterized...
			for api in ('QVariant', 'QString'):
				if sip.getapi(api) != 2:
					raise RuntimeError('%s API already set to V%d, but should be 2' % (api, sip.getapi(api)))
		else:
			sip.setapi("QString", 2)
			sip.setapi("QVariant", 2)

	def importMod(self, mod):
		if self._drv == 'PyQt4':
			self._initPyQt4()
		qt = __import__('%s.%s' % (self._drv, mod))
		return getattr(qt, mod)

	def __getattr__(self, name):
		if name.startswith('Qt'):
			return self.importMod(name)
		return super(QtDriver, self).__getattr__(name)

# --------------------------------------------------------------------

import numpy

def array2qimage_pure_python(arr):
	assert numpy.ndim(arr) == 3 and arr.shape[2] == 3
	h, w = arr.shape[:2]
	aligned = numpy.zeros((h, w, 4), numpy.uint8)
	aligned[:,:,2::-1] = arr
	result = QtGui.QImage(aligned.data, w, h, QtGui.QImage.Format_RGB32)
	return result.copy()

qt = QtDriver()
QtCore = qt.QtCore
QtGui = qt.QtGui
QtOpenGL = qt.QtOpenGL

if qt.name() == 'PySide':
	array2qimage = array2qimage_pure_python
	raw_view = None
else:
	from qimage2ndarray import array2qimage, raw_view
