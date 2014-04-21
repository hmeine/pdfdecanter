#  Copyright 2014-2014 Hans Meine <hans_meine@gmx.net>
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import sys, os

def getprop_PythonQt(prop):
	"""getprop(property_or_getter)

	Used on getters that have the same name as a corresponding
	property.  For PythonQt, this version will just return the
	argument, which is assumed to be (the value of) a python property
	through which PythonQt exposes Qt properties."""
	return prop

def getprop_other(getter):
	"""getprop(property_or_getter)

	Used on getters that have the same name as a corresponding
	property.  For Qt bindings other than PythonQt, this version will
	return the result of calling the argument, which is assumed to be
	a Qt getter function.  (With PythonQt, properties override getters
	and no calling must be done.)"""
	return getter()

class QtDriver(object):
	DRIVERS = ('PyQt4', 'PySide', 'PythonQt')
	
	@classmethod
	def detect_qt(cls):
		for drv in cls.DRIVERS:
			if drv in sys.modules:
				return drv
		if '_PythonQt' in sys.modules:
			return 'PythonQt'
		return None

	def name(self):
		return self._drv

	def getprop(self):
		return getprop_PythonQt if self._drv == 'PythonQt' else getprop_other

	def __init__(self, drv = os.environ.get('QT_DRIVER')):
		"""Supports QT_API (used by ETS and ipython)"""
		if drv is None:
			drv = self.detect_qt()
		if drv is None:
			drv = os.environ.get('QT_API')
		if drv is None:
			drv = 'PyQt4' # default to PyQt4
		drv = {'pyside' : 'PySide', 'pyqt' : 'PyQt4'}.get(drv, drv) # map ETS syntax
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

	@staticmethod
	def _initPythonQt():
		import pythonqt_workarounds

	def importMod(self, mod):
		if self._drv == 'PyQt4':
			self._initPyQt4()
		if self._drv == 'PythonQt':
			self._initPythonQt()
		qt = __import__('%s.%s' % (self._drv, mod))
		return getattr(qt, mod)

	def __getattr__(self, name):
		if name.startswith('Qt'):
			return self.importMod(name)
		return super(QtDriver, self).__getattr__(name)

# --------------------------------------------------------------------

import numpy

qt = QtDriver()
QtCore = qt.QtCore
QtGui = qt.QtGui
QtOpenGL = qt.QtOpenGL
getprop = qt.getprop()

import qimage2ndarray
