from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterDateTime,
    QgsProcessingParameterEnum,  # Usar ENUM en lugar de MultipleSelection
    QgsProcessingParameterNumber,
    QgsProcessingException,
    QgsVectorFileWriter,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsWkbTypes,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMessageLog,
    Qgis
)
from qgis.PyQt.QtCore import QCoreApplication, QDateTime, QUrl
from qgis.PyQt.QtGui import QColor, QIcon
from datetime import datetime, timedelta
import os
import sys
import tempfile
import subprocess
import uuid

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

HOURS = [f"{h:02d}:00" for h in range(24)]


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


class ERA5Algorithm(QgsProcessingAlgorithm):

    INPUT = "INPUT"
    OUTPUT_DIR = "OUTPUT_DIR"
    START_DATE = "START_DATE"
    END_DATE = "END_DATE"
    VARIABLES = "VARIABLES"
    HOURS = "HOURS"
    OUTPUT_FORMAT = "OUTPUT_FORMAT"
    RESOLUTION = "RESOLUTION"

    def name(self):
        return "era5_extractor"

    def displayName(self):
        return "ERA5-Land Data Extractor - ASM"

    def shortHelpString(self):
        
        base_dir = os.path.dirname(__file__)
        img_path = os.path.abspath(
        os.path.join(base_dir, "Logo", "ERA5LOGO.png")
        )
        img_url = QUrl.fromLocalFile(img_path).toString()

        return f"""
        <p><img src="{img_url}" width="600"></p>
        <b>ERA5-Land Data Extractor - ASM</b>
        <p>This algorithm developed by the <a href="https://agrofood.unibs.it//" target="_blank">Agrofood Research Hub</a> from the University of Brescia in order to download the <a href="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-timeseries?tab=overview" target="_blank">Copertnicus ERA5-Land climate data</a>
        Extract ERA5-Land climate data for points or polygons.
        
        <b>Parameters:</b>
        • <b>Input Layer</b>: Point or Polygon vector layer
        • <b>Start/End Date</b>: Date range for extraction
        • <b>Variables</b>: Select multiple ERA5-Land variables (Ctrl+Click)
        • <b>Hours</b>: Select multiple UTC hours (Ctrl+Click)
        • <b>Output Format</b>: For polygons only (Raster or Vector Grid)
        • <b>Resolution</b>: For polygons only (~0.1° = 11km)
        
        <b>Output:</b>
        • Points → CSV file with extracted values
        • Polygons → Raster (GeoTIFF) or Vector Grid (GeoJSON) files
        
        <b>Note:</b> Requires CDS API credentials configured in ~/.cdsapirc
        """

    def createInstance(self):
        return ERA5Algorithm()

    def initAlgorithm(self, config=None):
        # Input layer (points or polygons)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                "Input Layer (Points or Polygons)",
                [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon]
            )
        )

        # Date range
        default_start = QDateTime.currentDateTime().addDays(-7)
        default_end = QDateTime.currentDateTime()
        
        self.addParameter(
            QgsProcessingParameterDateTime(
                self.START_DATE,
                "Start Date",
                type=QgsProcessingParameterDateTime.Date,
                defaultValue=default_start
            )
        )

        self.addParameter(
            QgsProcessingParameterDateTime(
                self.END_DATE,
                "End Date",
                type=QgsProcessingParameterDateTime.Date,
                defaultValue=default_end
            )
        )

        # Variables - usando ENUM con allowMultiple=True
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VARIABLES,
                "ERA5-Land Variables (Ctrl+Click for multiple)",
                options=ERA5_VARIABLES,
                allowMultiple=True,
                defaultValue=[0, 7, 18]  # Temperatura, precipitación, radiación solar
            )
        )

        # Hours - usando ENUM con allowMultiple=True
        self.addParameter(
            QgsProcessingParameterEnum(
                self.HOURS,
                "Hours UTC (Ctrl+Click for multiple)",
                options=HOURS,
                allowMultiple=True,
                defaultValue=list(range(24))  # Todas las horas por defecto
            )
        )

        # Output format (for polygons only)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMAT,
                "Output Format (for Polygons only)",
                options=["Raster (GeoTIFF)", "Vector Grid (GeoJSON)"],
                defaultValue=0,
                optional=False
            )
        )

        # Resolution (for polygons only)
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RESOLUTION,
                "Resolution in degrees (for Polygons only)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.1,
                minValue=0.01,
                maxValue=1.0,
                optional=False
            )
        )

        # Output directory
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                "Output Folder"
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Get parameters
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if not source:
            raise QgsProcessingException("Invalid input layer")

        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        if not output_dir:
            raise QgsProcessingException("Please specify an output folder")

        # Get dates
        start_date = self.parameterAsDateTime(parameters, self.START_DATE, context)
        end_date = self.parameterAsDateTime(parameters, self.END_DATE, context)
        
        start_str = start_date.toString("yyyy-MM-dd")
        end_str = end_date.toString("yyyy-MM-dd")

        # Get variables (ahora usando parameterAsEnums)
        var_indices = self.parameterAsEnums(parameters, self.VARIABLES, context)
        if not var_indices:
            raise QgsProcessingException("Please select at least one variable")
        
        variables = [ERA5_VARIABLES[i] for i in var_indices]

        # Get hours (ahora usando parameterAsEnums)
        hour_indices = self.parameterAsEnums(parameters, self.HOURS, context)
        if not hour_indices:
            raise QgsProcessingException("Please select at least one hour")
        
        hours = [f"{i:02d}" for i in hour_indices]

        # Get output format and resolution
        output_format_idx = self.parameterAsEnum(parameters, self.OUTPUT_FORMAT, context)
        output_format = "raster" if output_format_idx == 0 else "vector"
        resolution = self.parameterAsDouble(parameters, self.RESOLUTION, context)

        # Determine geometry type
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        geom_type = layer.geometryType()

        feedback.pushInfo(f"Geometry type: {geom_type}")
        feedback.pushInfo(f"Date range: {start_str} to {end_str}")
        feedback.pushInfo(f"Variables: {', '.join(variables)}")
        feedback.pushInfo(f"Hours: {', '.join(hours)}")

        # Process based on geometry type
        if geom_type == QgsWkbTypes.PointGeometry:
            return self.process_points(layer, variables, hours, start_str, end_str, 
                                      output_dir, context, feedback)
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            return self.process_polygons(layer, variables, hours, start_str, end_str, 
                                        output_dir, output_format, resolution, context, feedback)
        else:
            raise QgsProcessingException("Only Point and Polygon layers are supported")

    def process_points(self, layer, variables, hours, start_date, end_date, 
                      output_dir, context, feedback):
        """Process point layer"""
        feedback.pushInfo("Processing POINTS layer...")
        
        # Export to temporary GeoJSON
        tmp_points = os.path.join(
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
            layer, tmp_points, QgsProject.instance().transformContext(), save_options
        )

        if result_export[0] != QgsVectorFileWriter.NoError:
            raise QgsProcessingException(f"Export error: {result_export[1]}")

        # Prepare environment
        env = self.prepare_environment()
        python_real = get_python_executable()

        # Build command
        args = [
            python_real,
            WORKER_POINTS_PATH,
            "--points", tmp_points,
            "--start", start_date,
            "--end", end_date,
            "--hours", ",".join(hours),
            "--vars", ",".join(variables),
            "--out", output_dir
        ]

        feedback.pushInfo(f"Executing: {' '.join(args)}")

        # Execute worker
        try:
            process = subprocess.Popen(
                args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            csv_path = None
            
            # Read output
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                
                clean_line = line.strip()
                feedback.pushInfo(clean_line)
                
                if "RESULT_PATH:" in clean_line:
                    csv_path = clean_line.split("RESULT_PATH:")[1].strip()

            process.wait()
            
            # Clean up temp file
            if os.path.exists(tmp_points):
                os.remove(tmp_points)

            if process.returncode != 0:
                raise QgsProcessingException("Worker process failed")

            # Load CSV to QGIS
            if csv_path and os.path.exists(csv_path):
                self.load_csv_to_qgis(csv_path, feedback)
                feedback.pushInfo(f"✓ CSV loaded: {csv_path}")

            return {self.OUTPUT_DIR: output_dir}

        except Exception as e:
            raise QgsProcessingException(f"Execution error: {str(e)}")

    def process_polygons(self, layer, variables, hours, start_date, end_date, 
                        output_dir, output_format, resolution, context, feedback):
        """Process polygon layer"""
        feedback.pushInfo(f"Processing POLYGONS layer (format: {output_format})...")
        
        # Export to temporary GeoJSON
        tmp_polygons = os.path.join(
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
            layer, tmp_polygons, QgsProject.instance().transformContext(), save_options
        )

        if result_export[0] != QgsVectorFileWriter.NoError:
            raise QgsProcessingException(f"Export error: {result_export[1]}")

        # Prepare environment
        env = self.prepare_environment()
        python_real = get_python_executable()

        # Build command
        args = [
            python_real,
            WORKER_POLYGONS_PATH,
            "--polygons", tmp_polygons,
            "--start", start_date,
            "--end", end_date,
            "--hours", ",".join(hours),
            "--vars", ",".join(variables),
            "--out", output_dir,
            "--resolution", str(resolution),
            "--output-format", output_format
        ]

        feedback.pushInfo(f"Executing: {' '.join(args)}")

        # Execute worker
        try:
            process = subprocess.Popen(
                args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            raster_paths = []
            vector_paths = []
            
            # Read output
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                
                clean_line = line.strip()
                feedback.pushInfo(clean_line)
                
                if "RASTER_PATH:" in clean_line:
                    raster_path = clean_line.split("RASTER_PATH:")[1].strip()
                    raster_paths.append(raster_path)
                
                if "VECTOR_PATH:" in clean_line:
                    vector_path = clean_line.split("VECTOR_PATH:")[1].strip()
                    vector_paths.append(vector_path)

            process.wait()
            
            # Clean up temp file
            if os.path.exists(tmp_polygons):
                os.remove(tmp_polygons)

            if process.returncode != 0:
                raise QgsProcessingException("Worker process failed")

            # Load results to QGIS
            for raster_path in raster_paths:
                if os.path.exists(raster_path):
                    self.load_raster_to_qgis(raster_path, feedback)
            
            for vector_path in vector_paths:
                if os.path.exists(vector_path):
                    self.load_vector_to_qgis(vector_path, feedback)

            feedback.pushInfo(f"✓ Generated {len(raster_paths)} raster(s) and {len(vector_paths)} vector(s)")

            return {self.OUTPUT_DIR: output_dir}

        except Exception as e:
            raise QgsProcessingException(f"Execution error: {str(e)}")

    def prepare_environment(self):
        """Prepare environment for subprocess"""
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

    def load_csv_to_qgis(self, path, feedback):
        """Load CSV to QGIS project"""
        if not os.path.exists(path):
            return

        path = os.path.abspath(path).replace('\\', '/')
        file_name = os.path.basename(path)
        
        uri = f"file:///{path}?type=csv&maxFields=10000&detectTypes=yes&geomType=none"
        
        lyr = QgsVectorLayer(uri, file_name, "delimitedtext")
        
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
            feedback.pushInfo(f"✓ CSV layer added: {file_name}")
        else:
            feedback.reportError(f"Failed to load CSV: {path}")

    def load_raster_to_qgis(self, path, feedback):
        """Load raster to QGIS project"""
        if not os.path.exists(path):
            return
        
        file_name = os.path.basename(path)
        layer_name = os.path.splitext(file_name)[0]
        
        lyr = QgsRasterLayer(path, layer_name)
        
        if lyr.isValid():
            # Configure NoData transparency
            provider = lyr.dataProvider()
            if provider:
                provider.setNoDataValue(1, -9999.0)
                renderer = lyr.renderer()
                if renderer:
                    # Corregido: usar QColor en lugar de Qt.transparent
                    renderer.setNodataColor(QColor(0, 0, 0, 0))
            
            lyr.triggerRepaint()
            QgsProject.instance().addMapLayer(lyr)
            feedback.pushInfo(f"✓ Raster layer added: {layer_name}")
        else:
            feedback.reportError(f"Failed to load raster: {path}")

    def load_vector_to_qgis(self, path, feedback):
        """Load vector to QGIS project"""
        if not os.path.exists(path):
            return
        
        file_name = os.path.basename(path)
        layer_name = os.path.splitext(file_name)[0]
        
        lyr = QgsVectorLayer(path, layer_name, "ogr")
        
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
            feedback.pushInfo(f"✓ Vector layer added: {layer_name}")
        else:
            feedback.reportError(f"Failed to load vector: {path}")

    def icon(self):
        base_dir = os.path.dirname(__file__)
        icon_path = os.path.abspath(
        os.path.join(base_dir, "Logo", "ERA5ICON.png")
        )
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mIconRaster.svg")