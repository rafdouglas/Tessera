"""Tessera main plugin dialog."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QPushButton, QTextEdit,
    QCheckBox, QDoubleSpinBox, QSpinBox, QLabel
)
from qgis.gui import QgsMapLayerComboBox
from qgis.core import (
    QgsMapLayerProxyModel,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
)

from ..algorithms.percentage_split import PercentageSplitAlgorithm
from ..algorithms.replace_with_shape import ReplaceWithShapeAlgorithm
from ..algorithms.arrange_features import ArrangeFeaturesAlgorithm
from ..algorithms.grid_arrangement import GridArrangementAlgorithm
from ..algorithms.scale_by_value import ScaleByValueAlgorithm
from ..algorithms.sketchy_borders import SketchyBordersAlgorithm
from ..algorithms.snap_to_grid import SnapToGridAlgorithm
from ..algorithms.stripe_hatching import StripeHatchingAlgorithm
from ..algorithms.tile_fill import TileFillAlgorithm

_ALGORITHM_REGISTRY = {
    'Tile Fill': TileFillAlgorithm,
    'Percentage Split': PercentageSplitAlgorithm,
    'Stripe Hatching': StripeHatchingAlgorithm,
    'Snap to Grid': SnapToGridAlgorithm,
    'Sketchy Borders': SketchyBordersAlgorithm,
    'Scale by Value': ScaleByValueAlgorithm,
    'Replace with Shape': ReplaceWithShapeAlgorithm,
    'Arrange Features': ArrangeFeaturesAlgorithm,
    'Grid Arrangement': GridArrangementAlgorithm,
}


class TesseraDialog(QDialog):
    """Main dialog for Tessera plugin."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tessera")
        self.parameter_widgets = {}

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        self._setup_layer_combo(main_layout)
        self._setup_algorithm_combo(main_layout)
        self._setup_parameter_panel(main_layout)
        self._setup_buttons(main_layout)
        self._setup_log_area(main_layout)
        self._setup_style_checkbox(main_layout)

        self._build_parameter_widgets()
        self.algorithm_combo.currentTextChanged.connect(self._on_algorithm_changed)

    def _setup_layer_combo(self, layout):
        """Create and add the layer selection combo."""
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        layout.addWidget(QLabel("Input Layer:"))
        layout.addWidget(self.layer_combo)

    def _setup_algorithm_combo(self, layout):
        """Create and add the algorithm selection combo."""
        self.algorithm_combo = QComboBox()
        for name in _ALGORITHM_REGISTRY:
            self.algorithm_combo.addItem(name)
        layout.addWidget(QLabel("Algorithm:"))
        layout.addWidget(self.algorithm_combo)

    def _setup_parameter_panel(self, layout):
        """Create the parameter panel form layout."""
        self.parameter_form = QFormLayout()
        layout.addLayout(self.parameter_form)

    def _setup_buttons(self, layout):
        """Create Run and Open Processing Dialog buttons."""
        self.run_button = QPushButton("Run")
        layout.addWidget(self.run_button)

        self.processing_button = QPushButton("Open Processing Dialog")
        layout.addWidget(self.processing_button)

    def _setup_log_area(self, layout):
        """Create the log text area."""
        layout.addWidget(QLabel("Log:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    def _setup_style_checkbox(self, layout):
        """Create the apply default style checkbox."""
        self.style_checkbox = QCheckBox("Apply default style")
        layout.addWidget(self.style_checkbox)

    def _on_algorithm_changed(self, algorithm_name):
        """Rebuild parameter panel when algorithm selection changes."""
        self._build_parameter_widgets()

    def _build_parameter_widgets(self):
        """Build widgets for the current algorithm's parameters."""
        self._clear_parameter_widgets()

        algorithm_name = self.algorithm_combo.currentText()
        algorithm_cls = _ALGORITHM_REGISTRY.get(algorithm_name, TileFillAlgorithm)
        algorithm = algorithm_cls()
        algorithm.initAlgorithm()

        for param_def in algorithm.parameterDefinitions():
            param_name = param_def.name()

            if isinstance(param_def, (QgsProcessingParameterFeatureSource,
                                     QgsProcessingParameterFeatureSink)):
                continue

            if param_def.flags() & QgsProcessingParameterDefinition.FlagAdvanced:
                continue

            widget = self._create_widget_for_parameter(param_def)
            if widget is not None:
                self.parameter_widgets[param_name] = widget
                label = QLabel(param_def.description())
                self.parameter_form.addRow(label, widget)

    def _create_widget_for_parameter(self, param_def):
        """Create appropriate widget for a parameter definition."""
        if isinstance(param_def, QgsProcessingParameterField):
            combo = QComboBox()
            combo.setEditable(True)
            combo.setPlaceholderText("Select field...")
            return combo

        elif isinstance(param_def, QgsProcessingParameterEnum):
            combo = QComboBox()
            for option in param_def.options():
                combo.addItem(option)
            combo.setCurrentIndex(param_def.defaultValue())
            return combo

        elif isinstance(param_def, QgsProcessingParameterNumber):
            if param_def.dataType() == QgsProcessingParameterNumber.Double:
                spinbox = QDoubleSpinBox()
                spinbox.setDecimals(2)
                spinbox.setMinimum(param_def.minimum())
                max_val = param_def.maximum()
                if max_val == float('inf') or max_val > 999999.99:
                    max_val = 999999.99
                spinbox.setMaximum(max_val)
                spinbox.setValue(param_def.defaultValue())
                # Add unit suffix if applicable
                desc = param_def.description().lower()
                if 'map units' in desc:
                    spinbox.setSuffix(' mu')
                elif 'degrees' in desc:
                    spinbox.setSuffix(' °')
                return spinbox
            else:
                spinbox = QSpinBox()
                spinbox.setMinimum(int(param_def.minimum()))
                max_val = param_def.maximum()
                if max_val == float('inf') or max_val > 2147483647:
                    max_val = 2147483647
                spinbox.setMaximum(int(max_val))
                spinbox.setValue(param_def.defaultValue())
                # Add unit suffix if applicable
                desc = param_def.description().lower()
                if 'map units' in desc:
                    spinbox.setSuffix(' mu')
                elif 'degrees' in desc:
                    spinbox.setSuffix(' °')
                return spinbox

        elif isinstance(param_def, QgsProcessingParameterBoolean):
            checkbox = QCheckBox()
            checkbox.setChecked(param_def.defaultValue())
            return checkbox

        return None

    def _clear_parameter_widgets(self):
        """Clear existing parameter widgets from the form."""
        while self.parameter_form.count():
            child = self.parameter_form.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.parameter_widgets.clear()
