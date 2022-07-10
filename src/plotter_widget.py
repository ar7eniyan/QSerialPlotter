import typing
from collections.abc import Mapping
from abc import ABC, abstractmethod
from typing import Callable, TypeVar, Generic

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QXYSeries
from PySide6.QtCore import QElapsedTimer, QMargins, Qt, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QColorDialog, QFrame, QHBoxLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

T = TypeVar('T')


class ColoredListEdit(QWidget, Generic[T]):
    """
    Widget for editing a list of items, each of them has its own color.
    Allows adding and removing items, changing their colors.

    The widget is divided into two parts:
        - "Add" button, which has a list of items to add.
        - A list of added items, stored in a horizontal layout,
          each of them has a name, a color picker button and a "Remove" button.

    When a series is added to the main list, it is removed from the "Add" menu.
    And when a series is removed from the main list, it is added to the "Add" menu.
    Widget supports custom callbacks on adding and removing series.

    To use the widget, you need your own class that implements the ColoredListEdit.Item ABC.
    """

    class Item(ABC, Generic[T]):
        """
        Abstract class for items in the list.
        To use the list widget, you need to subclass Item.
        """
        item: T

        @abstractmethod
        def __init__(self, item: T):
            self.item = item

        @property
        @abstractmethod
        def name(self) -> str:
            pass

        @property
        @abstractmethod
        def color(self) -> QColor:
            pass

        @color.setter
        @abstractmethod
        def color(self, color: QColor):
            pass

        @abstractmethod
        def on_add(self) -> None:
            """This method is called when the item is added to the list."""
            pass

        @abstractmethod
        def on_remove(self) -> None:
            """This method is called when the item is removed from the list."""
            pass

    add_button: QToolButton
    add_menu: QMenu
    layout: QHBoxLayout

    def __init__(self, parent=None):
        super().__init__(parent)
        self.add_button = QToolButton(self)
        self.add_button.setObjectName("add_button")
        self.add_button.setIcon(QIcon.fromTheme("list-add"))
        self.add_menu = QMenu()
        self.add_button.setMenu(self.add_menu)
        self.add_button.setPopupMode(QToolButton.InstantPopup)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 0, 0, 0)
        self.layout.addWidget(self.add_button)
        self.layout.addStretch(2)

        self.setup_stylesheet()
        self.setMinimumHeight(26)

    def setup_stylesheet(self) -> None:
        back_color = self.palette().color(self.backgroundRole()).darker(120)
        hover_color = self.palette().color(self.backgroundRole())
        border_color = self.palette().color(self.backgroundRole()).lighter(150)

        stylesheet = (
            ".QFrame, QToolButton#color_picker_button, QToolButton#add_button {{ \n"
            "    background-color: {background};\n"
            "    border: 1px solid {border};\n"
            "}}\n"
            ""
            "QToolButton#remove_button:hover {{ \n"
            "    border: 1px solid {border};\n"
            "}}\n"
            ""
            "QToolButton#add_button::menu-indicator {{\n"
            "    image: none;\n"
            "}}\n"
            ""
            "QToolButton#color_picker_button:hover, QToolButton#add_button:hover, QToolButton#remove_button:hover {{ \n"
            "    background-color: {hover};\n"
            "}}\n"
            ""
            "QToolButton {{\n"
            "    border-radius: 3px;\n"
            "}}\n"
            ""
            ".QFrame {{\n"
            "    border-radius: 5px;\n"
            "}}\n"
            ""
            "QLabel {{\n"
            "    font-size: 11pt;\n"
            "}}\n"
        ).format(background=back_color.name(), border=border_color.name(), hover=hover_color.name())
        self.setStyleSheet(stylesheet)

    def add_choice(self, item: Item[T]) -> None:
        """
        Add an item to the "Add" menu.

        Args:
            item: The item to add.
        """
        action = self.add_button.menu().addAction(item.name)
        pixmap = QPixmap(12, 12)
        pixmap.fill(item.color)
        action.setIcon(QIcon(pixmap))

        def _on_add():
            self.add_menu.removeAction(action)
            self.add_item(item)
            item.on_add()

        action.triggered.connect(_on_add)

    def clear_choices(self) -> None:
        self.add_menu.clear()

    def add_item(self, item: Item[T]) -> None:
        """
        Add an item to the end of the list.

        Args:
            item: The item to add.
        """
        frame = QFrame()
        frame.setFrameShape(QFrame.Panel)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(2, 2, 2, 2)

        color_picker_button = QToolButton(frame)
        color_picker_button.setObjectName("color_picker_button")
        color_pixmap = QPixmap(12, 12)
        color_pixmap.fill(item.color)
        button_size = color_pixmap.size().grownBy(QMargins(4, 4, 4, 4))
        color_picker_button.setFixedSize(button_size)
        color_picker_button.setIcon(QIcon(color_pixmap))
        color_picker_button.clicked.connect(self._color_setter(item, color_picker_button))
        layout.addWidget(color_picker_button)

        series_name_label = QLabel(frame)
        series_name_label.setText(item.name)
        layout.addWidget(series_name_label)

        remove_button = QToolButton(frame)
        remove_button.setObjectName("remove_button")
        remove_button.setFixedSize(button_size)
        remove_button.setIcon(QIcon.fromTheme("list-remove"))
        remove_button.setAutoRaise(True)

        def _on_remove():
            # delete the item from the list and return it to the "Add" menu
            frame.deleteLater()
            self.add_choice(item)
            item.on_remove()

        remove_button.clicked.connect(_on_remove)
        layout.addWidget(remove_button)

        # add frame before "add" button and before spacer
        self.layout.insertWidget(self.layout.count() - 2, frame)

    def _color_setter(self, item: Item[T], button: QToolButton) -> Callable[[], None]:
        """
        Get a function that sets the color of the given item and updates the button color.
        For internal use.
        """
        def callback():
            # this line causes XCB error [QTBUG-56893], but works fine
            color = QColorDialog.getColor(item.color, self)
            if color.isValid():
                # set picked color to the item
                item.color = color
                # update color picker button
                new_icon = QPixmap(12, 12)
                new_icon.fill(color)
                button.setIcon(QIcon(new_icon))

        return callback


class SeriesItem(ColoredListEdit.Item[QXYSeries]):
    """
    Item for list edit widget that represents a data series.
    Each data series is bound to a QChart object.
    Implements the :class:`ColoredListEdit.Item` interface.
    """
    chart: QChart

    def __init__(self, item: QXYSeries, chart: QChart):
        super().__init__(item)
        self.chart = chart

    @property
    def name(self) -> str:
        return self.item.name()

    @property
    def color(self) -> QColor:
        return self.item.color()

    @color.setter
    def color(self, color: QColor) -> None:
        self.item.setColor(color)

    def on_add(self) -> None:
        """Add the series to the bound chart."""
        self.item.show()

    def on_remove(self) -> None:
        """Remove the series from the bound chart."""
        self.item.hide()
        self.item.clear()


class PlotterUi:
    """Helper class for creating :class:`PlotterWidget` UI."""

    chart_view: QChartView
    chart: QChart
    series_edit: ColoredListEdit
    layout: QVBoxLayout

    def setup_ui(self, parent: QWidget):
        self.layout = QVBoxLayout(parent)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.series_edit = ColoredListEdit(parent)
        self.layout.addWidget(self.series_edit, 0)

        self.chart = QChart(QChart.ChartTypeCartesian, None, Qt.WindowFlags())
        self.chart.legend().hide()
        self.chart_view = QChartView(self.chart, parent)
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.layout.addWidget(self.chart_view, 0)


class PlotterWidget(QWidget):
    """
    Custom widget for plotting multiple data series.

    Has chart view and series edit widget, which can be used to add and remove series.
    Uses QLineSeries as series type and QValueAxis as axis type.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = PlotterUi()
        self.ui.setup_ui(self)

        self.max_value: float = 0.0
        self.min_value: float = 0.0
        self.span_secs: float = 10.0
        self.running: bool = False

        self.timer = QElapsedTimer()
        self.timer.invalidate()

        self.ui.chart.addAxis(QValueAxis(), Qt.AlignBottom)
        self.ui.chart.addAxis(QValueAxis(), Qt.AlignLeft)
        self._chart_axis_x().setRange(0, self.span_secs)
        self._chart_axis_y().setRange(0, 0)

    def add_series(self, series: QLineSeries) -> None:
        """
        Add the data series to the list edit widget.
        From the list edit widget, the series can be added to the chart.
        """
        if series.chart() is self.ui.chart:
            return

        self.ui.chart.addSeries(series)
        series.attachAxis(self._chart_axis_x())
        series.attachAxis(self._chart_axis_y())
        self.ui.series_edit.add_choice(SeriesItem(series, self.ui.chart))

    @Slot(float)
    def set_timespan(self, secs: float) -> None:
        """
        Set the timespan of the plot.
        Args:
            secs: The timespan value in seconds.
        """
        self.span_secs = secs

    @Slot()
    def start_plotting(self) -> None:
        """
        Start plotting. Must be called before any calls to `update_plot()`.
        By default, new `PlotterWidget` instances are created stopped.
        """
        self.max_value = 0.0
        self.min_value = 0.0
        self.running = True

    @Slot()
    def stop_plotting(self) -> None:
        """
        Stop plotting and clear the chart. After this call, subsequent calls to plot_data
        will no longer be accepted until `start_plotting()` is called.
        """
        self.running = False
        self._chart_axis_y().setRange(0, 0)
        self._chart_axis_x().setRange(0, self.span_secs)
        map(lambda series: series.clear(), self.ui.chart.series())
        self.timer.invalidate()

    @Slot()
    def reset_plot(self) -> None:
        """
        Reset the plot to its initial state.
        Equivalent to calling `stop_plotting()` and then `start_plotting()`.
        """
        self.stop_plotting()
        self.start_plotting()

    @Slot(Mapping)
    def plot_values(self, values: Mapping[str, float]) -> None:
        """
        Plot the given values on chart. Updates X and Y axis ranges.
        Args:
            values: Mapping with data to plot in format {series_object_name: value}.
        """
        if not self.running:
            return

        if not self.timer.isValid():
            self.timer.start()
            elapsed = 0
        else:
            elapsed = self.timer.elapsed() / 1000

        for series in self.ui.chart.series():  # type: QLineSeries
            # remove points that no longer create visible lines
            # doing in one remove call is faster than removing one by one
            i = 0
            while i < series.count() - 1:
                if series.at(i + 1).x() < elapsed - self.span_secs:
                    i += 1
                else:
                    break
            series.removePoints(0, i)

            if series.objectName() not in values:
                continue
            series.append(elapsed, values[series.objectName()])

            # update Y axis range only for series that are visible
            if not series.isVisible():
                continue

            self.max_value = max(self.max_value, max(values.values()))
            self.min_value = min(self.min_value, min(values.values()))
            self._chart_axis_y().setRange(self.min_value * 1.1, self.max_value * 1.1)

        # and update X axis range for it to be [elapsed - span_secs, elapsed],
        # make sure range start is positive and its length is equal to span_secs
        if elapsed > self.span_secs:
            self._chart_axis_x().setRange(elapsed - self.span_secs, elapsed)
        else:
            self._chart_axis_x().setRange(0, self.span_secs)

    def _chart_axis_y(self) -> QValueAxis:
        return typing.cast(QValueAxis, self.ui.chart.axes(Qt.Vertical)[0])

    def _chart_axis_x(self) -> QValueAxis:
        return typing.cast(QValueAxis, self.ui.chart.axes(Qt.Horizontal)[0])
