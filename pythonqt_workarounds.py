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
