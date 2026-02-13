import os
import requests
import tempfile

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterString,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterEnum,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsFeatureSink,
    QgsProject,
    QgsEditFormConfig,
    QgsAttributeEditorContainer,
    QgsAttributeEditorField,
    QgsProcessingException,
    QgsEditorWidgetSetup,
    QgsSettings,
    QgsProcessingContext
)

from PyQt5.QtCore import QVariant, Qt, QUrl
from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QBrush, QFont, QIcon
from PyQt5.QtWidgets import QMessageBox, QInputDialog, QLineEdit, QApplication

class PlantNetApiConfigurator:

    @staticmethod
    def setup_credentials():
        parent = QApplication.activeWindow()
        profile_url = "https://my.plantnet.org/"

        # Mensaje informativo previo con link
        msg = QMessageBox(parent)
        msg.setWindowTitle("PlantNet API Setup")
        msg.setIcon(QMessageBox.Information)
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            f"To obtain your <b>Pl@ntNet API Key</b>, visit:<br>"
            f"<a href='{profile_url}'>{profile_url}</a><br><br>"
            f"Copy your personal API Key and paste it in the next step."
        )
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)

        if msg.exec_() == QMessageBox.Cancel:
            return None

        # Pedir la API key
        key, ok = QInputDialog.getText(
            parent,
            "Ingresar API Key",
            "Pega tu API Key de Pl@ntNet:",
            QLineEdit.Password
        )

        if ok and key:
            clean_key = key.strip().replace('"', '').replace("'", "")
            settings = QgsSettings()
            settings.setValue('plantnet/api_key', clean_key)

            QMessageBox.information(
                parent,
                "Éxito",
                "API Key guardada correctamente en la configuración de QGIS."
            )

            return clean_key

        return None

class PlantNetIdentifyMultiOrgan(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    CHART_FOLDER = "CHART_FOLDER"
    CENTER_IMAGE = "CENTER_IMAGE"
    
    # Órganos soportados por PlantNet
    ORGANS = ['leaf', 'flower', 'fruit', 'bark', 'habit']
    ORGAN_LABELS = ['Hoja (leaf)', 'Flor (flower)', 'Fruto (fruit)', 'Tronco (bark)', 'Hábito (habit)', 'Auto (primera disponible)']

    def name(self): 
        return "plantnet_identify_multi_organ_ASM"
    
    def displayName(self): 
        return "Plantnet Multiorgan Identification - ASM"
    
    def group(self): 
        return None
    
    def groupId(self): 
        return None
    
    def shortHelpString(self):
        
        base_dir = os.path.dirname(__file__)
        img_path = os.path.abspath(
        os.path.join(base_dir, "..", "Logo", "PNILOGO.png")
        )
        img_url = QUrl.fromLocalFile(img_path).toString()

        return f"""
        <p><img src="{img_url}" width="600"></p>
        <h3>Plant identification with Pl@ntNet (Multi-Organ)</h3>

        <p>This algorithm developed by the <a href="https://agrofood.unibs.it//" target="_blank">Agrofood Research Hub</a> from the University of Brescia uses the <a href="https://my.plantnet.org/" target="_blank">Pl@ntNet</a> API to identify plant species 
        from up to 5 images per point, each corresponding to a different organ:</p>
        <ul>
            <li><b>leaf</b>: Leaf image</li>
            <li><b>flower</b>: Flower image</li>
            <li><b>fruit</b>: Fruit image</li>
            <li><b>bark</b>: Trunk/bark image</li>
            <li><b>habit</b>: Image of general habit/appearance</li>
        </ul>
        <p>The input layer must have fields with these exact names containing 
        the paths to the images. Fields may be empty if no image is available.</p>
        <p><b>Note:</b> According to PlantNet, the order of importance of the organs is: 
        flower > fruit > leaf > habit > bark</p>
        """

    def get_stored_api_key(self):
        """Busca la API key en diferentes ubicaciones de configuración de QGIS"""
        from qgis.core import QgsSettings
        
        settings = QgsSettings()
        
        # Lista de posibles ubicaciones donde puede estar guardada la API key
        possible_keys = [
            # Configuración específica de PlantNet
            'plantnet/api_key',
            'PlantNet/api_key',
            'plantnet/apikey',
            'PlantNet/apiKey',
            # Processing
            'Processing/configuration/PLANTNET_API_KEY',
            'Processing/configuration/plantnet_api_key',
            # Plugins
            'plugins/plantnet/api_key',
            'plugins/PlantNet/api_key',
            # Configuración general
            'qgis/plantnet_api_key',
            'PLANTNET_API_KEY',
        ]
        
        for key in possible_keys:
            value = settings.value(key, None)
            if value and str(value).strip():
                return str(value).strip()
        
        # También buscar en variables de entorno
        import os
        env_key = os.environ.get('PLANTNET_API_KEY', None)
        if env_key:
            return env_key
        
        # Buscar en archivo de configuración en el perfil de usuario
        config_file = os.path.join(
            os.path.dirname(QgsSettings().fileName()),
            'plantnet_api_key.txt'
        )
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    key = f.read().strip()
                    if key:
                        return key
            except:
                pass
        
        return None

    def save_api_key(self, api_key):
        """Guarda la API key en la configuración de QGIS para uso futuro"""
        from qgis.core import QgsSettings
        settings = QgsSettings()
        settings.setValue('plantnet/api_key', api_key)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                "Input layer (points with fields: leaf, flower, fruit, bark, habit)",
                [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CENTER_IMAGE,
                "Central image of the doughnut chart",
                options=self.ORGAN_LABELS,
                defaultValue=5  # Auto (primera disponible)
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.CHART_FOLDER,
                "Carpeta para guardar gráficos",
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, 
                "Layer with results"
            )
        )

    def generate_chart_image(self, center_image_path, species, scores, others, output_path):
        """Genera una imagen JPG del gráfico de donut - ESTILO ACTUALIZADO"""
        
        # Crear imagen
        width, height = 700, 520
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor(44, 44, 44))  # Fondo gris oscuro
        
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        # Configuración del donut - CENTRADO horizontal y vertical
        center_x, center_y = width // 2, 200  # Centro horizontal y vertical superior
        outer_radius = 120
        inner_radius = 75
        
        # Colores
        colors = [
            QColor(76, 175, 80),   # Verde
            QColor(33, 150, 243),  # Azul
            QColor(255, 152, 0),   # Naranja
            QColor(156, 39, 176),  # Púrpura
            QColor(244, 67, 54)    # Rojo
        ]
        
        # Dibujar segmentos del donut
        start_angle = 90 * 16
        
        for i, (score, color) in enumerate(zip(scores, colors)):
            if score > 0:
                span_angle = int(-score * 360 * 16)
                
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor(30, 30, 30), 3))
                
                painter.drawPie(
                    center_x - outer_radius, 
                    center_y - outer_radius, 
                    outer_radius * 2, 
                    outer_radius * 2, 
                    start_angle, 
                    span_angle
                )
                
                start_angle += span_angle
        
        # Añadir segmento de "otros" si existe
        if others > 0:
            span_angle = int(-others * 360 * 16)
            painter.setBrush(QBrush(QColor(158, 158, 158)))  # Gris
            painter.setPen(QPen(QColor(30, 30, 30), 3))
            painter.drawPie(
                center_x - outer_radius, 
                center_y - outer_radius, 
                outer_radius * 2, 
                outer_radius * 2, 
                start_angle, 
                span_angle
            )
        
        # Dibujar borde exterior
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(20, 20, 20), 4))
        painter.drawEllipse(
            center_x - outer_radius, 
            center_y - outer_radius, 
            outer_radius * 2, 
            outer_radius * 2
        )
        
        # Dibujar círculo interior
        painter.setBrush(QBrush(QColor(44, 44, 44)))
        painter.setPen(QPen(QColor(20, 20, 20), 4))
        painter.drawEllipse(
            center_x - inner_radius, 
            center_y - inner_radius, 
            inner_radius * 2, 
            inner_radius * 2
        )
        
        # Cargar y dibujar imagen central
        if center_image_path and os.path.exists(center_image_path):
            plant_img = QImage(center_image_path)
            if not plant_img.isNull():
                size = inner_radius * 2 - 8
                scaled_img = plant_img.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                
                # Crear máscara circular
                circular_img = QImage(size, size, QImage.Format_ARGB32)
                circular_img.fill(Qt.transparent)
                
                circle_painter = QPainter(circular_img)
                circle_painter.setRenderHint(QPainter.Antialiasing)
                circle_painter.setBrush(QBrush(scaled_img))
                circle_painter.setPen(Qt.NoPen)
                circle_painter.drawEllipse(0, 0, size, size)
                circle_painter.end()
                
                painter.drawImage(center_x - size//2, center_y - size//2, circular_img)
        
        # LEYENDA EN DOS FILAS EN LA PARTE INFERIOR
        valid_species = [(sp, sc, color) for sp, sc, color in zip(species, scores, colors) if sp]
        
        # Agregar "Others" si existe
        if others > 0:
            valid_species.append(("Others", others, QColor(158, 158, 158)))
        
        # Configuración de leyenda
        legend_start_y = 370  # Posición Y inicio (parte inferior)
        row_spacing = 55      # Más espacio entre filas para nombres largos
        box_size = 18
        
        # Determinar cuántos items por fila para mejor distribución
        total_items = len(valid_species)
        if total_items <= 3:
            items_per_row = total_items
        elif total_items <= 6:
            items_per_row = 3
        else:
            items_per_row = 4
        
        # Ancho de cada item - ajustado para mejor centrado
        item_width = 225
        
        # Calcular número de filas
        num_rows = (total_items + items_per_row - 1) // items_per_row
        
        for idx, (species_name, score, color) in enumerate(valid_species):
            row = idx // items_per_row
            col = idx % items_per_row
            
            # Calcular cuántos items hay en esta fila específica
            items_in_this_row = min(items_per_row, total_items - row * items_per_row)
            
            # Calcular ancho total de esta fila
            row_total_width = items_in_this_row * item_width
            
            # Centrar la fila horizontalmente
            row_start_x = (width - row_total_width) // 2 + 10
            
            x_pos = row_start_x + col * item_width
            y_pos = legend_start_y + row * row_spacing
            
            # Cuadro de color
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(20, 20, 20), 2))
            painter.drawRect(x_pos, y_pos, box_size, box_size)
            
            # Preparar nombre - dividir en líneas si es muy largo
            max_chars_per_line = 25  # Nombres científicos pueden ser más largos
            species_lines = []
            
            if len(species_name) <= max_chars_per_line:
                species_lines.append(species_name)
            else:
                # Dividir en palabras (por espacios)
                words = species_name.split()
                current_line = ""
                
                for word in words:
                    if len(current_line) + len(word) + 1 <= max_chars_per_line:
                        current_line += (word + " ")
                    else:
                        if current_line:
                            species_lines.append(current_line.strip())
                        current_line = word + " "
                
                if current_line:
                    species_lines.append(current_line.strip())
            
            # Dibujar nombre (con saltos de línea si es necesario)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor(255, 255, 255))
            font_bold = QFont("Segoe UI", 10, QFont.Bold)
            painter.setFont(font_bold)
            
            text_x = x_pos + box_size + 8
            
            for line_idx, line in enumerate(species_lines):
                text_y = y_pos + 13 + (line_idx * 15)
                painter.drawText(text_x, text_y, line)
            
            # Porcentaje - ajustar posición según número de líneas
            font_normal = QFont("Segoe UI", 9)
            painter.setFont(font_normal)
            painter.setPen(QColor(200, 200, 200))
            
            percentage_y = y_pos + 13 + (len(species_lines) * 15)
            painter.drawText(text_x, percentage_y, f"({score*100:.1f}%)")
        
        painter.end()
        image.save(output_path, "JPG", 95)
        return output_path

    def get_available_images(self, feat):
        """Obtiene las imágenes disponibles y sus órganos correspondientes"""
        images = {}
        for organ in self.ORGANS:
            try:
                image_path = feat.attribute(organ)
                if image_path and str(image_path).strip() and os.path.exists(str(image_path)):
                    images[organ] = str(image_path)
            except:
                pass
        return images

    def select_center_image(self, images, preference):
        """Selecciona la imagen para el centro del gráfico según la preferencia"""
        if preference < 5:  # Se seleccionó un órgano específico
            organ = self.ORGANS[preference]
            if organ in images:
                return images[organ]
        
        # Auto: usar orden de prioridad de PlantNet
        priority_order = ['flower', 'fruit', 'leaf', 'habit', 'bark']
        for organ in priority_order:
            if organ in images:
                return images[organ]
        
        return None

    def processAlgorithm(self, parameters, context, feedback):     
        source = self.parameterAsSource(parameters, self.INPUT, context)

        if source is None:
            raise QgsProcessingException(
                "The input layer could not be loaded."
                "Ensure you select a valid point layer."
        )

        chart_folder = self.parameterAsString(parameters, self.CHART_FOLDER, context)
        center_image_pref = self.parameterAsEnum(parameters, self.CENTER_IMAGE, context)
        
        api_key = self.get_stored_api_key()

        if not api_key:
            api_key = PlantNetApiConfigurator.setup_credentials()

        if not api_key:
            raise QgsProcessingException(
                "Se requiere una API Key válida de Pl@ntNet para continuar."
            )

        # Guardar para usos futuros
        self.save_api_key(api_key)
        feedback.pushInfo("API key configurada correctamente.")
        
        # Verificar que la capa tenga al menos uno de los campos de órgano
        field_names = [f.name().lower() for f in source.fields()]
        available_organ_fields = [o for o in self.ORGANS if o in field_names]
        
        if not available_organ_fields:
            raise QgsProcessingException(
                f"The layer must have at least one of these fields: {', '.join(self.ORGANS)}"
            )
        
        feedback.pushInfo(f"Organ fields found: {', '.join(available_organ_fields)}")
        
        # Crear carpeta para gráficos
        if not chart_folder:
            chart_folder = os.path.join(tempfile.gettempdir(), "plantnet_charts")
        
        if not os.path.exists(chart_folder):
            os.makedirs(chart_folder)
            
        feedback.pushInfo(f"Saving graphics in: {chart_folder}")
        
        # Crear campos de salida
        fields = QgsFields()
        fields.append(QgsField("ID", QVariant.Int))
        
        # Campo coverage de la capa original
        fields.append(QgsField("coverage", QVariant.Double))
        
        # Campos para las 5 imágenes de órganos
        for organ in self.ORGANS:
            fields.append(QgsField(organ, QVariant.String))
        
        # Campo para indicar qué imagen se usó en el centro
        fields.append(QgsField("center_img", QVariant.String))
        
        # Campos para resultados de especies
        for i in range(1, 6):
            fields.append(QgsField(f"sp_{i}", QVariant.String))
            fields.append(QgsField(f"sc_{i}", QVariant.Double))
        
        fields.append(QgsField("others", QVariant.Double))
        fields.append(QgsField("chart", QVariant.String))
        fields.append(QgsField("n_images", QVariant.Int))  # Número de imágenes usadas

        (sink, dest_id) = self.parameterAsSink(
            parameters, 
            self.OUTPUT, 
            context, 
            fields, 
            source.wkbType(), 
            source.sourceCrs()
        )

        # Procesar cada feature
        url = "https://my-api.plantnet.org/v2/identify/all"
        total = source.featureCount()
        
        for idx, feat in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break
            
            feedback.setProgress(int((idx / total) * 100))
            
            # Obtener imágenes disponibles
            images = self.get_available_images(feat)
            
            if not images:
                feedback.pushWarning(f"Feature {idx}: No valid images were found.")
                continue
            
            feedback.pushInfo(f"Feature {idx}: Images found for organs: {list(images.keys())}")
            
            # Preparar llamada a la API con múltiples imágenes
            file_handles = []
            try:
                files = []
                organs_list = []
                
                for organ, path in images.items():
                    fh = open(path, "rb")
                    file_handles.append(fh)
                    files.append(("images", fh))
                    organs_list.append(organ)
                
                data = {"organs": organs_list}
                params = {"api-key": api_key}
                
                response = requests.post(url, files=files, data=data, params=params, timeout=60)
                
                # Cerrar archivos
                for fh in file_handles:
                    fh.close()
                file_handles = []
                
                response.raise_for_status()
                results = response.json().get("results", [])
                
            except requests.exceptions.RequestException as e:
                feedback.pushWarning(f"Error in API for feature {idx}: {str(e)}")
                for fh in file_handles:
                    try:
                        fh.close()
                    except:
                        pass
                continue
            except Exception as e:
                feedback.pushWarning(f"Error processing feature {idx}: {str(e)}")
                for fh in file_handles:
                    try:
                        fh.close()
                    except:
                        pass
                continue

            # Crear feature de salida
            out_feat = QgsFeature(fields)
            out_feat.setGeometry(feat.geometry())
            
            # Preparar datos de especies
            species = []
            scores = []
            total_score = 0.0
            
            for i in range(5):
                if i < len(results):
                    sp = results[i]["species"]["scientificName"]
                    sc = float(results[i]["score"])
                else:
                    sp = ""
                    sc = 0.0
                
                species.append(sp)
                scores.append(sc)
                total_score += sc
            
            others = max(0.0, 1.0 - total_score)
            
            # Seleccionar imagen central
            center_image = self.select_center_image(images, center_image_pref)
            
            # Generar gráfico
            chart_filename = f"chart_{idx}.jpg"
            chart_path = os.path.join(chart_folder, chart_filename)
            self.generate_chart_image(center_image, species, scores, others, chart_path)
            
            # Preparar atributos
            vals = [idx]
            
            # Obtener coverage de la feature original
            try:
                coverage_val = feat.attribute("coverage")
                if coverage_val is None or coverage_val == "NULL":
                    coverage_val = None
            except:
                coverage_val = None
            vals.append(coverage_val)
            
            # Añadir rutas de imágenes de órganos
            for organ in self.ORGANS:
                vals.append(images.get(organ, ""))
            
            # Imagen central usada
            center_organ = ""
            for organ, path in images.items():
                if path == center_image:
                    center_organ = organ
                    break
            vals.append(center_organ)
            
            # Resultados de especies
            for sp, sc in zip(species, scores):
                vals.extend([sp, sc])
            
            vals.append(others)
            vals.append(chart_path)
            vals.append(len(images))  # Número de imágenes usadas
            
            out_feat.setAttributes(vals)
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)
            
            if results:
                feedback.pushInfo(f"Feature {idx} processed: {results[0]['species']['scientificName']} (using {len(images)} images)")
            else:
                feedback.pushInfo(f"Feature {idx} processed: No results")

        # Guardar dest_id para postProcessAlgorithm
        self.dest_id = dest_id
            
        return {self.OUTPUT: dest_id}

    def postProcessAlgorithm(self, context, feedback):
        """Configure the form after the layer is fully loaded"""
        
        # Obtener la capa de salida
        layer = QgsProcessingContext.takeResultLayer(context, self.dest_id)
        
        if layer:
            self.configure_form(layer)
            feedback.pushInfo("Formulario configurado correctamente con 3 pestañas")
            
            # Añadir la capa al proyecto
            QgsProject.instance().addMapLayer(layer)
            
        return {self.OUTPUT: self.dest_id}

    def configure_form(self, layer):
        """Configura el formulario con 3 pestañas: Datos, Imágenes, Gráfico"""
        
        # Primero configurar los widgets de los campos ANTES de crear el formulario
        # Esto es crítico para que QGIS reconozca los tipos de widget
        
        # Configurar widgets de imagen para los órganos
        for organ in self.ORGANS:
            field_idx = layer.fields().indexOf(organ)
            if field_idx >= 0:
                widget_config = {
                    'DocumentViewer': 1,
                    'DocumentViewerHeight': 300,
                    'DocumentViewerWidth': 400,
                    'FileWidget': True,
                    'FileWidgetButton': True,
                    'FileWidgetFilter': 'Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)',
                    'RelativeStorage': 0,
                    'StorageMode': 0,
                    'UseLink': False,
                    'FullUrl': False
                }
                setup = QgsEditorWidgetSetup('ExternalResource', widget_config)
                layer.setEditorWidgetSetup(field_idx, setup)
        
        # Configurar widget para el gráfico
        chart_idx = layer.fields().indexOf("chart")
        if chart_idx >= 0:
            chart_config = {
                'DocumentViewer': 1,
                'DocumentViewerHeight': 520,
                'DocumentViewerWidth': 700,
                'FileWidget': True,
                'FileWidgetButton': False,
                'FileWidgetFilter': 'Images (*.jpg *.jpeg *.png)',
                'RelativeStorage': 0,
                'StorageMode': 0,
                'UseLink': False,
                'FullUrl': False
            }
            setup = QgsEditorWidgetSetup('ExternalResource', chart_config)
            layer.setEditorWidgetSetup(chart_idx, setup)
        
        # Ahora configurar el layout del formulario con pestañas
        config = layer.editFormConfig()
        config.setLayout(QgsEditFormConfig.TabLayout)
        
        # Limpiar contenedor raíz
        root = config.invisibleRootContainer()
        root.clear()
        
        # ============================================
        # PESTAÑA 1: DATOS
        # ============================================
        tab_data = QgsAttributeEditorContainer("Datos", root)
        tab_data.setIsGroupBox(False)
        
        # Grupo de identificación
        id_container = QgsAttributeEditorContainer("Identificación", tab_data)
        id_container.setIsGroupBox(True)
        
        id_idx = layer.fields().indexOf("ID")
        if id_idx >= 0:
            id_field = QgsAttributeEditorField("ID", id_idx, id_container)
            id_container.addChildElement(id_field)
        
        n_images_idx = layer.fields().indexOf("n_images")
        if n_images_idx >= 0:
            n_images_field = QgsAttributeEditorField("n_images", n_images_idx, id_container)
            id_container.addChildElement(n_images_field)
        
        center_idx = layer.fields().indexOf("center_img")
        if center_idx >= 0:
            center_field = QgsAttributeEditorField("center_img", center_idx, id_container)
            id_container.addChildElement(center_field)
        
        tab_data.addChildElement(id_container)
        
        # Grupo de resultados PlantNet
        species_container = QgsAttributeEditorContainer("Results PlantNet", tab_data)
        species_container.setIsGroupBox(True)
        
        for i in range(1, 6):
            sp_idx = layer.fields().indexOf(f"sp_{i}")
            sc_idx = layer.fields().indexOf(f"sc_{i}")
            if sp_idx >= 0:
                sp_field = QgsAttributeEditorField(f"sp_{i}", sp_idx, species_container)
                species_container.addChildElement(sp_field)
            if sc_idx >= 0:
                sc_field = QgsAttributeEditorField(f"sc_{i}", sc_idx, species_container)
                species_container.addChildElement(sc_field)
        
        others_idx = layer.fields().indexOf("others")
        if others_idx >= 0:
            others_field = QgsAttributeEditorField("others", others_idx, species_container)
            species_container.addChildElement(others_field)
        
        tab_data.addChildElement(species_container)
        
        # ============================================
        # PESTAÑA 2: IMÁGENES
        # ============================================
        tab_images = QgsAttributeEditorContainer("Imágenes", root)
        tab_images.setIsGroupBox(False)
        
        organ_names = {
            'leaf': 'Hoja (leaf)',
            'flower': 'Flor (flower)', 
            'fruit': 'Fruto (fruit)',
            'bark': 'Tronco (bark)',
            'habit': 'Hábito (habit)'
        }
        
        for organ in self.ORGANS:
            field_idx = layer.fields().indexOf(organ)
            if field_idx >= 0:
                # Crear contenedor/grupo para cada imagen
                img_container = QgsAttributeEditorContainer(organ_names.get(organ, organ), tab_images)
                img_container.setIsGroupBox(True)
                
                img_field = QgsAttributeEditorField(organ, field_idx, img_container)
                img_container.addChildElement(img_field)
                tab_images.addChildElement(img_container)
        
        # ============================================
        # PESTAÑA 3: GRÁFICO
        # ============================================
        tab_chart = QgsAttributeEditorContainer("Gráfico", root)
        tab_chart.setIsGroupBox(False)
        
        if chart_idx >= 0:
            chart_field = QgsAttributeEditorField("chart", chart_idx, tab_chart)
            tab_chart.addChildElement(chart_field)
        
        # Añadir pestañas al root en orden
        root.addChildElement(tab_data)
        root.addChildElement(tab_images)
        root.addChildElement(tab_chart)
        
        # Aplicar configuración
        layer.setEditFormConfig(config)

    def createInstance(self): 
        return PlantNetIdentifyMultiOrgan()
    
    def icon(self):
        base_dir = os.path.dirname(__file__)
        icon_path = os.path.abspath(
        os.path.join(base_dir, "..", "Logo", "PNIICON.png")
        )
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mIconRaster.svg")