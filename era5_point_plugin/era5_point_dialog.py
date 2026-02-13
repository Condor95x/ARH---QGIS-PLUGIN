import os
import sys
import tempfile
import subprocess
import uuid
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QMessageBox,
    QListWidget, QListWidgetItem, QFileDialog,
    QDateEdit, QProgressBar, QCheckBox, QGridLayout,
    QWidget, QInputDialog, QButtonGroup, QRadioButton,
    QLineEdit
)
from qgis.PyQt.QtCore import Qt, QDate, QTimer
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsMessageLog, Qgis,
    QgsRasterLayer
)

class CDSApiConfigurator:
    @staticmethod
    def setup_credentials(parent):
        path = os.path.expanduser("~/.cdsapirc")
        profile_url = "https://cds.climate.copernicus.eu/profile?tab=profile"
        
        # Mensaje informativo previo con el link
        msg = QMessageBox(parent)
        msg.setWindowTitle("CDS API Setup")
        msg.setIcon(QMessageBox.Information)
        msg.setTextFormat(Qt.RichText)  # Para que el link sea clickable
        msg.setText(
            f"To get your API Key, please visit your <b>CDS Profile</b>:<br>"
            f"<a href='{profile_url}'>{profile_url}</a><br><br>"
            f"Copy the <b>Key</b> string shown at the bottom of that page."
        )
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        
        if msg.exec_() == QMessageBox.Cancel:
            return False

        # Pedir la KEY (UID:API-KEY)
        key, ok = QInputDialog.getText(parent, "Enter API Key", 
            "Paste your CDS API Key (Format: UID:KEY):", QLineEdit.Normal)
        
        if ok and key:
            try:
                # Limpiar la clave por si el usuario copió espacios o comillas
                clean_key = key.strip().replace('"', '').replace("'", "")
                
                with open(path, 'w', encoding='utf-8') as f:
                    f.write("url: https://cds.climate.copernicus.eu/api\n")
                    f.write(f"key: {clean_key}\n")
                
                QMessageBox.information(parent, "Success", "Credentials saved successfully to ~/.cdsapirc")
                return True
            except Exception as e:
                QMessageBox.critical(parent, "Error", f"Could not save file: {e}")
                return False
        return False
    
def get_python_executable():
    """Busca el ejecutable de python real dentro de la estructura de QGIS"""
    bin_dir = os.path.dirname(sys.executable)
    potential_exes = [
        os.path.join(bin_dir, "python3.exe"),
        os.path.join(bin_dir, "python.exe"),
        os.path.join(bin_dir, "..", "bin", "python3.exe"),
    ]
    for exe in potential_exes:
        if os.path.exists(exe):
            return exe
    return sys.executable

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_POINTS_PATH = os.path.join(PLUGIN_DIR, "worker", "era5_worker.py")
WORKER_POLYGONS_PATH = os.path.join(PLUGIN_DIR, "worker", "era5_polygon_worker.py")

ERA5_VARIABLES = [
    "2m_temperature", "2m_dewpoint_temperature", "skin_temperature",
    "soil_temperature_level_1", "soil_temperature_level_2",
    "soil_temperature_level_3", "soil_temperature_level_4",
    "total_precipitation", "total_evaporation", "potential_evaporation",
    "snowfall", "snow_depth", "snow_albedo", "snow_melt",
    "volumetric_soil_water_layer_1", "volumetric_soil_water_layer_2",
    "volumetric_soil_water_layer_3", "volumetric_soil_water_layer_4",
    "surface_solar_radiation_downwards", "surface_net_solar_radiation",
    "surface_thermal_radiation_downwards", "surface_net_thermal_radiation",
    "10m_u_component_of_wind", "10m_v_component_of_wind",
    "surface_pressure", "leaf_area_index_high_vegetation",
    "leaf_area_index_low_vegetation", "runoff"
]

class ERA5ExtractorDialog(QDialog):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.setWindowTitle("ERA5-Land Extractor - Points & Polygons")
        self.resize(550, 750)
        self.output_dir = None
        self.final_csv_path = None
        self.output_rasters = []
        self.output_vectors = []
        self.process = None
        self.timer = None
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout()

        # ===============================
        # Input layer
        # ===============================
        layout.addWidget(QLabel("<b>Input Layer:</b>"))

        self.layer_combo = QComboBox()
        layout.addWidget(self.layer_combo)

        # ===============================
        # Geometry type label
        # ===============================
        self.geom_type_label = QLabel("<i>Geometry type: Unknown</i>")
        layout.addWidget(self.geom_type_label)

        # ===============================
        # Date range
        # ===============================
        dates_layout = QHBoxLayout()

        self.start_date = QDateEdit(QDate.currentDate().addDays(-7))
        self.start_date.setCalendarPopup(True)

        self.end_date = QDateEdit(QDate.currentDate())
        self.end_date.setCalendarPopup(True)

        dates_layout.addWidget(QLabel("Start Date:"))
        dates_layout.addWidget(self.start_date)
        dates_layout.addWidget(QLabel("End Date:"))
        dates_layout.addWidget(self.end_date)

        layout.addLayout(dates_layout)

        # ===============================
        # Hours
        # ===============================
        layout.addWidget(QLabel("<b>Hours (UTC):</b>"))

        quick_layout = QHBoxLayout()
        btn_all = QPushButton("Select All")
        btn_none = QPushButton("Select None")

        self.hour_checkboxes = []
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self.hour_checkboxes])
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb in self.hour_checkboxes])

        quick_layout.addWidget(btn_all)
        quick_layout.addWidget(btn_none)
        layout.addLayout(quick_layout)

        hours_grid = QGridLayout()

        for h in range(24):
            hour_str = f"{h:02d}:00"
            cb = QCheckBox(hour_str)
            cb.setChecked(True)

            row = h % 6
            col = h // 6
            hours_grid.addWidget(cb, row, col)
            self.hour_checkboxes.append(cb)

        layout.addLayout(hours_grid)

        # ===============================
        # Variables
        # ===============================
        layout.addWidget(QLabel("<b>Variables ERA5-Land:</b>"))

        var_buttons_layout = QHBoxLayout()
        btn_select_all_vars = QPushButton("Select All")
        btn_deselect_all_vars = QPushButton("Deselect All")
        
        btn_select_all_vars.clicked.connect(self.select_all_variables)
        btn_deselect_all_vars.clicked.connect(self.deselect_all_variables)
        
        var_buttons_layout.addWidget(btn_select_all_vars)
        var_buttons_layout.addWidget(btn_deselect_all_vars)
        layout.addLayout(var_buttons_layout)

        self.var_list = QListWidget()
        self.var_list.setSelectionMode(QListWidget.MultiSelection)

        for var in ERA5_VARIABLES:
            item = QListWidgetItem(var)
            item.setCheckState(Qt.Unchecked)
            self.var_list.addItem(item)

        layout.addWidget(self.var_list)

        # ===============================
        # Polygon options
        # ===============================
        self.polygon_options_widget = QWidget()
        poly_layout = QVBoxLayout()

        poly_layout.addWidget(QLabel("<b>Output Format (for Polygons):</b>"))
        
        # Radio buttons para elegir formato
        format_info = QLabel(
            "<i>• <b>Raster</b>: GeoTIFF files (data masked to polygon)<br>"
            "• <b>Vector Grid</b>: Show ERA5 pixel grid with values as attributes</i>"
        )
        format_info.setWordWrap(True)
        poly_layout.addWidget(format_info)
        
        self.format_button_group = QButtonGroup()
        self.raster_radio = QRadioButton("Raster (GeoTIFF)")
        self.vector_radio = QRadioButton("Vector Grid (GeoJSON)")
        
        self.raster_radio.setChecked(True)  # Por defecto
        
        self.format_button_group.addButton(self.raster_radio)
        self.format_button_group.addButton(self.vector_radio)
        
        poly_layout.addWidget(self.raster_radio)
        poly_layout.addWidget(self.vector_radio)
        
        # Nota sobre resolución
        res_note = QLabel(
            "<i>Note: ERA5-Land has ~11km resolution (~0.1°). "
            "Vector grid shows the actual ERA5 pixels that intersect your polygon.</i>"
        )
        res_note.setWordWrap(True)
        poly_layout.addWidget(res_note)

        self.polygon_options_widget.setLayout(poly_layout)
        self.polygon_options_widget.setVisible(False)
        layout.addWidget(self.polygon_options_widget)

        # ===============================
        # Output folder
        # ===============================
        out_layout = QHBoxLayout()

        self.out_label = QLabel("<i>No folder selected</i>")
        btn_out = QPushButton("Select Folder")
        btn_out.clicked.connect(self.select_output)

        out_layout.addWidget(self.out_label)
        out_layout.addWidget(btn_out)
        layout.addLayout(out_layout)

        # ===============================
        # Progress bar
        # ===============================
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)
        # Botón de configuración
        self.btn_config_api = QPushButton("⚙️ Setup CDS Credentials")
        self.btn_config_api.clicked.connect(lambda: CDSApiConfigurator.setup_credentials(self))
        layout.addWidget(self.btn_config_api)
        # ===============================
        # Run button
        # ===============================
        self.run_button = QPushButton("🚀 Run Extraction")
        self.run_button.setStyleSheet("font-weight: bold; height: 40px;")
        self.run_button.clicked.connect(self.run)
        layout.addWidget(self.run_button)

        # ===============================
        # Final layout
        # ===============================
        self.setLayout(layout)

        # ===============================
        # Señales + datos iniciales
        # ===============================
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        self.populate_layers()
        self.on_layer_changed()

    def select_all_variables(self):
        """Selecciona todas las variables"""
        for i in range(self.var_list.count()):
            self.var_list.item(i).setCheckState(Qt.Checked)

    def deselect_all_variables(self):
        """Deselecciona todas las variables"""
        for i in range(self.var_list.count()):
            self.var_list.item(i).setCheckState(Qt.Unchecked)

    def populate_layers(self):
        """Carga capas de puntos y polígonos"""
        self.layer_combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                geom_type = layer.geometryType()
                if geom_type in [QgsWkbTypes.PointGeometry, QgsWkbTypes.PolygonGeometry]:
                    self.layer_combo.addItem(layer.name(), layer)

    def on_layer_changed(self):
        """Actualiza la UI según el tipo de geometría de la capa seleccionada"""
        layer = self.layer_combo.currentData()
        if not layer:
            self.geom_type_label.setText("<i>Geometry type: Unknown</i>")
            self.polygon_options_widget.setVisible(False)
            return
        
        geom_type = layer.geometryType()
        
        if geom_type == QgsWkbTypes.PointGeometry:
            self.geom_type_label.setText("<i>Geometry type: <b>Points</b> → Will extract to CSV</i>")
            self.polygon_options_widget.setVisible(False)
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            self.geom_type_label.setText("<i>Geometry type: <b>Polygons</b> → Will generate Rasters</i>")
            self.polygon_options_widget.setVisible(True)
        else:
            self.geom_type_label.setText("<i>Geometry type: Unsupported</i>")
            self.polygon_options_widget.setVisible(False)

    def select_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Output Folder")
        if folder:
            self.output_dir = folder
            self.out_label.setText(folder)

    def get_checked_items(self, list_widget):
        return [list_widget.item(i).text() for i in range(list_widget.count()) 
                if list_widget.item(i).checkState() == Qt.Checked]

    def get_selected_hours(self):
        selected = []
        for cb in self.hour_checkboxes:
            if cb.isChecked():
                hour_val = cb.text().split(":")[0]
                selected.append(hour_val)
        return selected

    def run(self):
        layer = self.layer_combo.currentData()
        variables = self.get_checked_items(self.var_list)
        hours = self.get_selected_hours()
        
        if not layer:
            QMessageBox.warning(self, "Missing data", "Please select a layer.")
            return
        
        if not variables:
            QMessageBox.warning(self, "Missing data", "Please select at least one variable.")
            return
        
        if not hours:
            QMessageBox.warning(self, "Missing data", "Please select at least one hour.")
            return
        
        if not self.output_dir:
            QMessageBox.warning(self, "Missing data", "Please select an output folder.")
            return

        geom_type = layer.geometryType()
        
        if geom_type == QgsWkbTypes.PointGeometry:
            self.run_points_extraction(layer, variables, hours)
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            self.run_polygon_extraction(layer, variables, hours)
        else:
            QMessageBox.warning(self, "Unsupported", "Only Point and Polygon layers are supported.")

    def run_points_extraction(self, layer, variables, hours):
        """Extracción para puntos"""
        self.tmp_points = os.path.join(
            tempfile.gettempdir(),
            f"era5_points_{uuid.uuid4().hex}.geojson"
        )
        
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = "GeoJSON"
        save_options.ct = QgsCoordinateTransform(
            layer.crs(), 
            QgsCoordinateReferenceSystem("EPSG:4326"), 
            QgsProject.instance()
        )
       
        result_export = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, self.tmp_points, QgsProject.instance().transformContext(), save_options
        )

        if result_export[0] != QgsVectorFileWriter.NoError:
            QMessageBox.critical(self, "Export Error", f"Error: {result_export[1]}")
            return

        env = self.prepare_environment()
        python_real = get_python_executable()

        args = [
            python_real,
            WORKER_POINTS_PATH,
            "--points", self.tmp_points,
            "--start", self.start_date.date().toPyDate().isoformat(),
            "--end", self.end_date.date().toPyDate().isoformat(),
            "--hours", ",".join(hours),
            "--vars", ",".join(variables),
            "--out", self.output_dir
        ]

        self.execute_process(args, env, "points")

    def run_polygon_extraction(self, layer, variables, hours):
        """Extracción para polígonos"""
        self.tmp_polygons = os.path.join(
            tempfile.gettempdir(),
            f"era5_polygons_{uuid.uuid4().hex}.geojson"
        )
        
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = "GeoJSON"
        save_options.ct = QgsCoordinateTransform(
            layer.crs(), 
            QgsCoordinateReferenceSystem("EPSG:4326"), 
            QgsProject.instance()
        )
       
        result_export = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, self.tmp_polygons, QgsProject.instance().transformContext(), save_options
        )

        if result_export[0] != QgsVectorFileWriter.NoError:
            QMessageBox.critical(self, "Export Error", f"Error: {result_export[1]}")
            return

        env = self.prepare_environment()
        python_real = get_python_executable()
        
        # Determinar formato de salida
        output_format = "vector" if self.vector_radio.isChecked() else "raster"

        args = [
            python_real,
            WORKER_POLYGONS_PATH,
            "--polygons", self.tmp_polygons,
            "--start", self.start_date.date().toPyDate().isoformat(),
            "--end", self.end_date.date().toPyDate().isoformat(),
            "--hours", ",".join(hours),
            "--vars", ",".join(variables),
            "--out", self.output_dir,
            "--resolution", "0.1",
            "--output-format", output_format
        ]

        self.execute_process(args, env, "polygons")

    def prepare_environment(self):
        """Prepara el entorno para el subproceso"""
        env = os.environ.copy()
        env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
        python_path = os.pathsep.join(sys.path)
        env["PYTHONPATH"] = python_path

        qgis_bin = os.path.dirname(sys.executable)
        qgis_root = os.path.abspath(os.path.join(qgis_bin, ".."))
        
        env["PROJ_LIB"] = os.path.join(qgis_root, "share", "proj")
        env["GDAL_DATA"] = os.path.join(qgis_root, "share", "gdal")
        env["PATH"] = qgis_bin + os.pathsep + env.get("PATH", "")
        
        return env
    
    def execute_process(self, args, env, mode):
        """Ejecuta el proceso worker"""
        try:
            self.current_mode = mode
            self.output_rasters = []  # Limpiar lista de rasters
            self.output_vectors = []  # Limpiar lista de vectores
            
            self.process = subprocess.Popen(
                args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            self.progress_bar.setVisible(True)
            self.run_button.setEnabled(False)
            self.run_button.setText("⏳ Processing...")

            self.timer = QTimer()
            self.timer.timeout.connect(self.read_process_output)
            self.timer.start(100)
            
        except Exception as e:
            QMessageBox.critical(self, "Execution Error", f"Could not start worker: {str(e)}")
            self.cleanup_ui()
    
    def read_process_output(self):
        if self.process and self.process.stdout:
            while True:
                line = self.process.stdout.readline()
                if not line: 
                    break
                
                clean_line = line.strip()
                QgsMessageLog.logMessage(f"WORKER: {clean_line}", "ERA5", Qgis.Info)

                if "RESULT_PATH:" in clean_line:
                    path_parts = clean_line.split("RESULT_PATH:")
                    if len(path_parts) > 1:
                        self.final_csv_path = path_parts[1].strip()
                
                if "RASTER_PATH:" in clean_line:
                    path_parts = clean_line.split("RASTER_PATH:")
                    if len(path_parts) > 1:
                        raster_path = path_parts[1].strip()
                        self.output_rasters.append(raster_path)
                
                if "VECTOR_PATH:" in clean_line:
                    path_parts = clean_line.split("VECTOR_PATH:")
                    if len(path_parts) > 1:
                        vector_path = path_parts[1].strip()
                        self.output_vectors.append(vector_path)
                
                if "Solicitando" in clean_line or "Downloading" in clean_line:
                    self.run_button.setText("⏳ Downloading from ERA5...")
                
                if "Generating" in clean_line or "Procesando" in clean_line:
                    self.run_button.setText("⏳ Generating rasters...")

        if self.process and self.process.poll() is not None:
            if self.timer:
                self.timer.stop()
            self.on_process_finished()

    def on_process_finished(self):
        exit_code = self.process.poll() if self.process else -1
        self.cleanup_ui()

        # Limpiar archivos temporales
        if hasattr(self, 'tmp_points') and os.path.exists(self.tmp_points):
            try:
                os.remove(self.tmp_points)
            except:
                pass
        
        if hasattr(self, 'tmp_polygons') and os.path.exists(self.tmp_polygons):
            try:
                os.remove(self.tmp_polygons)
            except:
                pass

        if exit_code == 0:
            if self.current_mode == "points":
                if self.final_csv_path and os.path.exists(self.final_csv_path):
                    self.load_csv_to_qgis(self.final_csv_path)
                QMessageBox.information(self, "Success", "Point extraction completed and loaded.")
            
            elif self.current_mode == "polygons":
                loaded_rasters = 0
                loaded_vectors = 0
                
                for raster_path in self.output_rasters:
                    if os.path.exists(raster_path):
                        self.load_raster_to_qgis(raster_path)
                        loaded_rasters += 1
                
                for vector_path in self.output_vectors:
                    if os.path.exists(vector_path):
                        self.load_vector_to_qgis(vector_path)
                        loaded_vectors += 1
                
                if loaded_rasters > 0:
                    msg = f"Polygon extraction completed.\n{loaded_rasters} raster(s) loaded to QGIS."
                elif loaded_vectors > 0:
                    msg = f"Polygon extraction completed.\n{loaded_vectors} vector grid(s) loaded to QGIS."
                else:
                    msg = "Polygon extraction completed."
                
                QMessageBox.information(self, "Success", msg)
                self.output_rasters = []
                self.output_vectors = []
        else:
            QMessageBox.critical(self, "Error", 
                "Extraction failed. Check the QGIS Log Panel (View > Panels > Log Messages) for details.")

    def cleanup_ui(self):
        """Restaura el estado de la UI"""
        self.progress_bar.setVisible(False)
        self.run_button.setEnabled(True)
        self.run_button.setText("🚀 Run Extraction")

    def load_csv_to_qgis(self, path):
        """Carga el CSV al proyecto"""
        if not os.path.exists(path):
            return

        path = os.path.abspath(path).replace('\\', '/')
        file_name = os.path.basename(path)
        
        uri = f"file:///{path}?type=csv&maxFields=10000&detectTypes=yes&geomType=none"
        
        lyr = QgsVectorLayer(uri, file_name, "delimitedtext")
        
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
            self.iface.showAttributeTable(lyr)
        else:
            QgsMessageLog.logMessage(f"Failed to load CSV: {uri}", "ERA5", Qgis.Warning)

    def load_raster_to_qgis(self, path):
        """Carga un raster al proyecto y configura transparencia NoData"""
        if not os.path.exists(path):
            return
        
        file_name = os.path.basename(path)
        layer_name = os.path.splitext(file_name)[0]
        
        lyr = QgsRasterLayer(path, layer_name)
        
        if lyr.isValid():
            # Configurar el valor NoData como transparente
            provider = lyr.dataProvider()
            if provider:
                # Establecer NoData en el proveedor
                provider.setNoDataValue(1, -9999.0)
                
                # Configurar transparencia en el renderer
                renderer = lyr.renderer()
                if renderer:
                    renderer.setNodataColor(Qt.transparent)
            
            # Refrescar la capa
            lyr.triggerRepaint()
            
            QgsProject.instance().addMapLayer(lyr)
            QgsMessageLog.logMessage(f"Raster loaded: {layer_name}", "ERA5", Qgis.Info)
        else:
            QgsMessageLog.logMessage(f"Failed to load raster: {path}", "ERA5", Qgis.Warning)
    
    def load_vector_to_qgis(self, path):
        """Carga una capa vectorial al proyecto"""
        if not os.path.exists(path):
            return
        
        file_name = os.path.basename(path)
        layer_name = os.path.splitext(file_name)[0]
        
        lyr = QgsVectorLayer(path, layer_name, "ogr")
        
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
            QgsMessageLog.logMessage(f"Vector grid loaded: {layer_name}", "ERA5", Qgis.Info)
        else:
            QgsMessageLog.logMessage(f"Failed to load vector: {path}", "ERA5", Qgis.Warning)