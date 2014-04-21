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

from PythonQt import QtCore, QtGui

def QSizeF___rmul__(size, factor):
	return size * factor

def QColor_getRgb(color):
	return color.red(), color.green(), color.blue()

_orig_setEasingCurve = QtCore.QVariantAnimation.setEasingCurve
def QVariantAnimation_setEasingCurve(anim, ec):
	if not isinstance(ec, QtCore.QEasingCurve):
		ec = QtCore.QEasingCurve(ec)
	return _orig_setEasingCurve(anim, ec)

QtCore.QSizeF.__rmul__ = QSizeF___rmul__
QtGui.QColor.getRgb = QColor_getRgb
QtCore.QVariantAnimation.setEasingCurve = QVariantAnimation_setEasingCurve
