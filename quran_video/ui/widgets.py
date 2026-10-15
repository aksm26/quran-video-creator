"""Small widget helpers: controls that ignore the mouse wheel, sliders that jump to a click, and the font picker."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QListWidget, QSlider, QStyle, QStyledItemDelegate,
                               QStyleOptionSlider, QStyleOptionViewItem, QVBoxLayout)

POPUP_ROWS = 8  # how many entries every dropdown shows before it scrolls
FAMILY_ROLE = Qt.ItemDataRole.UserRole + 1
SAMPLE_ROLE = Qt.ItemDataRole.UserRole + 2


class NoWheelCombo(QComboBox):
    """Scrolling over it scrolls the panel instead of changing the choice. Its list is always the same height."""

    def __init__(self):
        super().__init__()
        self.setMaxVisibleItems(POPUP_ROWS)

    def wheelEvent(self, e):
        e.ignore()


class VerseCombo(NoWheelCombo):
    """A dropdown of verse numbers 1..maximum. It offers a spin box's methods (value, setValue, setMaximum,
    valueChanged), so the window can treat it like one."""

    valueChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._max = 0
        self.setMaximum(1)
        self.currentIndexChanged.connect(lambda i: self.valueChanged.emit(self.value()) if i >= 0 else None)

    def value(self) -> int:
        return self.currentIndex() + 1

    def setValue(self, v: int) -> None:
        self.setCurrentIndex(min(max(v, 1), self._max) - 1)

    def maximum(self) -> int:
        return self._max

    def setMaximum(self, n: int) -> None:
        if n == self._max:
            return
        keep = self.value() if self._max else 1
        was = self.blockSignals(True)  # the caller decides whether this counts as a change
        self.clear()
        self.addItems([str(i) for i in range(1, n + 1)])
        self._max = n
        self.setCurrentIndex(min(keep, n) - 1)
        self.blockSignals(was)


class NoWheelSlider(QSlider):
    """Ignores the wheel, and a click anywhere on the bar moves the handle there (it can then be dragged on)."""

    def wheelEvent(self, e):
        e.ignore()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            slider = QStyle.ComplexControl.CC_Slider
            groove = self.style().subControlRect(slider, opt, QStyle.SubControl.SC_SliderGroove, self)
            handle = self.style().subControlRect(slider, opt, QStyle.SubControl.SC_SliderHandle, self)
            span = max(1, groove.width() - handle.width())
            pos = int(e.position().x()) - groove.x() - handle.width() // 2
            self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos, span, opt.upsideDown))
        super().mousePressEvent(e)


class FontDelegate(QStyledItemDelegate):
    """Draws the font's name on the left and a sample of it, in that font, on the right."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name, family, sample = opt.text, index.data(FAMILY_ROLE), index.data(SAMPLE_ROLE) or ""
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)  # background, selection
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        painter.save()
        painter.setPen(QColor(opt.palette.color(role)))
        area = opt.rect.adjusted(12, 0, -12, 0)
        painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        if family and sample:
            font = QFont(family)
            font.setPixelSize(24)
            painter.setFont(font)
            painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, sample)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 44)


class ListPopup(QFrame):
    """A short list that drops down from a button: at most POPUP_ROWS rows tall, then it scrolls (wheel or bar)."""

    chosen = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("listpopup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda item: (self.hide(), self.chosen.emit(item.data(Qt.ItemDataRole.UserRole))))
        lay.addWidget(self.list)

    def labels(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def show_below(self, button, items: list[tuple[str, object]], current) -> None:
        self.list.clear()
        for label, data in items:
            self.list.addItem(label)
            self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, data)
            if data == current:
                self.list.setCurrentRow(self.list.count() - 1)
        row = max(28, self.list.sizeHintForRow(0))
        self.resize(max(button.width(), 240), min(len(items), POPUP_ROWS) * row + 12)
        left_to_right = self.layoutDirection() == Qt.LayoutDirection.LeftToRight
        # Open under the button, lined up with its outer edge (the right one, or the left one in RTL languages).
        below = button.mapToGlobal(button.rect().bottomRight() if left_to_right else button.rect().bottomLeft())
        x = below.x() - (self.width() if left_to_right else 0)
        self.move(x, below.y() + 4)
        self.show()
        self.list.scrollToItem(self.list.currentItem())
