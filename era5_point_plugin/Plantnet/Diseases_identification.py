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
    """Configurador de credenciales de PlantNet API"""
    
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


class PlantNetDiseaseIdentifier(QgsProcessingAlgorithm):
    """
    Algoritmo para identificación de enfermedades de plantas usando PlantNet API.
    Utiliza el endpoint /v2/diseases/identify para detectar patologías.
    """
    
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    CHART_FOLDER = "CHART_FOLDER"
    IMAGE_FIELD = "IMAGE_FIELD"
    
    # Diccionario de traducción de códigos EPPO a nombres comunes en inglés
    # Fuente: Base de datos EPPO Global Database
    EPPO_DISEASE_NAMES = {
        # Enfermedades de vid (Vitis)
        'PLASVI': 'Downy mildew',
        'ERYSNE': 'Powdery mildew', 
        'BOTRCI': 'Gray mold (Botrytis)',
        'PHAEAC': 'Petri disease',
        'PHACHL': 'Black foot disease',
        'EUTYAR': 'Eutypa dieback',
        'DIAAMP': 'Black rot',
        'GUIGBI': 'Black rot',
        'ARMAME': 'White rot',
        
        # Enfermedades comunes en otras plantas
        'PHYTIN': 'Late blight',
        'PHYTCA': 'Phytophthora capsici',
        'PYTHSP': 'Pythium spp.',
        'FUSAOX': 'Fusarium oxysporum',
        'VERTICL': 'Verticillium wilt',
        'SCATAU': 'Anthracnose',
        'PSDMSY': 'Downy mildew',
        'ALTERSO': 'Alternaria',
        'COLLAG': 'Anthracnose',
        'SEPTTR': 'Septoria leaf spot',
        'XANTHCA': 'Bacterial spot',
        'ERWIAM': 'Fire blight',
        'PSDMTA': 'Bacterial speck',
        'AGRBTU': 'Crown gall',
        'RALSSO': 'Bacterial wilt',
        'CLAVPU': 'Rust',
        'PUCCGR': 'Cereal rust',
        'HEMIVA': 'Coffee rust',
    }
    
    def name(self): 
        return "plantnet_disease_identifier_ASM"
    
    def displayName(self): 
        return "PlantNet Disease Identification - ASM"

    def shortHelpString(self):

        base_dir = os.path.dirname(__file__)
        img_path = os.path.abspath(
        os.path.join(base_dir, "..", "Logo", "PNDLOGO.png")
        )
        img_url = QUrl.fromLocalFile(img_path).toString()

        return f"""
        <p><img src="{img_url}" width="600"></p>
        <h3>Plant Disease Identification with Pl@ntNet</h3>
        <p>This algorithm developed by the <a href="https://agrofood.unibs.it//" target="_blank">Agrofood Research Hub</a> from the University of Brescia uses the <a href="https://my.plantnet.org/" target="_blank">Pl@ntNet</a> API to identify plant diseases from images.</p>

        <p><b>Requirements:</b></p>
        <ul>
            <li>Input layer must be point vector layer</li>
            <li>Must have a field containing image file paths</li>
            <li>Valid Pl@ntNet API key (obtained from https://my.plantnet.org/)</li>
        </ul>
        
        <p><b>API Endpoint:</b> /v2/diseases/identify</p>
        
        <p><b>Output:</b></p>
        <ul>
            <li>Up to 5 most probable diseases with confidence scores</li>
            <li>Disease names (translated from EPPO codes)</li>
            <li>Donut chart showing probability distribution</li>
            <li>Links to disease information (EPPO database)</li>
        </ul>
        
        <p><b>Note:</b> PlantNet's disease database is limited. Not all plant diseases 
        or hosts may be covered. Check available diseases at the API documentation.</p>
        """

    def get_stored_api_key(self):
        """Busca la API key en diferentes ubicaciones de configuración de QGIS"""
        settings = QgsSettings()
        
        # Lista de posibles ubicaciones donde puede estar guardada la API key
        possible_keys = [
            'plantnet/api_key',
            'PlantNet/api_key',
            'plantnet/apikey',
            'PlantNet/apiKey',
            'Processing/configuration/PLANTNET_API_KEY',
            'Processing/configuration/plantnet_api_key',
            'plugins/plantnet/api_key',
            'plugins/PlantNet/api_key',
            'qgis/plantnet_api_key',
            'PLANTNET_API_KEY',
        ]
        
        for key in possible_keys:
            value = settings.value(key, None)
            if value and str(value).strip():
                return str(value).strip()
        
        # También buscar en variables de entorno
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
        settings = QgsSettings()
        settings.setValue('plantnet/api_key', api_key)
    
    def get_disease_name(self, eppo_code):
        """Obtiene el nombre común de la enfermedad desde el código EPPO"""
        if not eppo_code:
            return ""
        
        # Buscar en diccionario local
        name = self.EPPO_DISEASE_NAMES.get(eppo_code, "")
        
        if name:
            return name
        
        # Si no está en el diccionario, devolver el código con formato más legible
        # Quitar números y hacer más legible
        formatted = eppo_code.replace('_', ' ').title()
        return formatted

    def initAlgorithm(self, config=None):
        """Inicialización de parámetros del algoritmo"""
        
        # Capa de entrada
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                "Input layer (points with disease images)",
                [QgsProcessing.TypeVectorPoint]
            )
        )
        
        # Campo que contiene la ruta de las imágenes
        self.addParameter(
            QgsProcessingParameterString(
                self.IMAGE_FIELD,
                "Field name containing image paths",
                defaultValue="image"
            )
        )
        
        # Carpeta para guardar gráficos
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.CHART_FOLDER,
                "Folder to save disease charts",
                optional=True
            )
        )
        
        # Capa de salida
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, 
                "Output layer with disease results"
            )
        )

    def generate_disease_donut_chart(self, image_path, diseases, scores, eppo_codes, output_path):
        """Genera un gráfico de dona tipo PlantNet especies para enfermedades"""
        
        # Crear imagen - mismas dimensiones que especies
        width, height = 700, 520
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor(44, 44, 44))  # Fondo gris oscuro igual que especies
        
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        # Configuración del donut - CENTRADO horizontal y vertical
        center_x, center_y = width // 2, 200  # Centro horizontal y vertical superior
        outer_radius = 120
        inner_radius = 75
        
        # Colores (paleta diferente para enfermedades - tonos más cálidos/alertas)
        colors = [
            QColor(220, 53, 69),   # Rojo (enfermedad principal)
            QColor(255, 152, 0),   # Naranja
            QColor(255, 193, 7),   # Amarillo
            QColor(156, 39, 176),  # Púrpura
            QColor(33, 150, 243)   # Azul
        ]
        
        # Calcular "others"
        total_score = sum(scores)
        others = max(0.0, 1.0 - total_score)
        
        # Dibujar segmentos del donut
        start_angle = 90 * 16  # Empezar arriba
        
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
        
        # Cargar y dibujar imagen central (circular como en especies)
        if image_path and os.path.exists(image_path):
            plant_img = QImage(image_path)
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
        valid_diseases = [(d, s, e, c) for d, s, e, c in zip(diseases, scores, eppo_codes, colors) if d and s > 0]
        
        # Agregar "Others" si existe
        if others > 0:
            valid_diseases.append(("Others", others, "", QColor(158, 158, 158)))
        
        # Configuración de leyenda - MEJORADA
        legend_start_y = 370  # Posición Y inicio (parte inferior)
        row_spacing = 55      # Más espacio entre filas para nombres largos
        box_size = 18
        
        # Determinar cuántos items por fila para mejor distribución
        total_items = len(valid_diseases)
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
        
        for idx, (disease, score, eppo, color) in enumerate(valid_diseases):
            row = idx // items_per_row
            col = idx % items_per_row
            
            # Calcular cuántos items hay en esta fila específica
            items_in_this_row = min(items_per_row, total_items - row * items_per_row)
            
            # Calcular ancho total de esta fila
            row_total_width = items_in_this_row * item_width
            
            # Centrar la fila horizontalmente - AJUSTADO
            # Restar un pequeño offset para compensar el ancho de los cuadros y texto
            row_start_x = (width - row_total_width) // 2 + 10
            
            x_pos = row_start_x + col * item_width
            y_pos = legend_start_y + row * row_spacing
            
            # Cuadro de color
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(20, 20, 20), 2))
            painter.drawRect(x_pos, y_pos, box_size, box_size)
            
            # Preparar nombre - dividir en líneas si es muy largo
            max_chars_per_line = 20
            disease_lines = []
            
            if len(disease) <= max_chars_per_line:
                disease_lines.append(disease)
            else:
                # Dividir en palabras
                words = disease.split()
                current_line = ""
                
                for word in words:
                    if len(current_line) + len(word) + 1 <= max_chars_per_line:
                        current_line += (word + " ")
                    else:
                        if current_line:
                            disease_lines.append(current_line.strip())
                        current_line = word + " "
                
                if current_line:
                    disease_lines.append(current_line.strip())
            
            # Dibujar nombre (con saltos de línea si es necesario)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor(255, 255, 255))
            font_bold = QFont("Segoe UI", 10, QFont.Bold)
            painter.setFont(font_bold)
            
            text_x = x_pos + box_size + 8
            
            for line_idx, line in enumerate(disease_lines):
                text_y = y_pos + 13 + (line_idx * 15)
                painter.drawText(text_x, text_y, line)
            
            # Porcentaje - ajustar posición según número de líneas
            font_normal = QFont("Segoe UI", 9)
            painter.setFont(font_normal)
            painter.setPen(QColor(200, 200, 200))
            
            percentage_y = y_pos + 13 + (len(disease_lines) * 15)
            painter.drawText(text_x, percentage_y, f"({score*100:.1f}%)")
        
        painter.end()
        image.save(output_path, "JPG", 95)
        return output_path

    def processAlgorithm(self, parameters, context, feedback):
        """Proceso principal del algoritmo"""
        
        # Obtener parámetros
        source = self.parameterAsSource(parameters, self.INPUT, context)
        
        if source is None:
            raise QgsProcessingException(
                "No se pudo cargar la capa de entrada. "
                "Asegúrese de seleccionar una capa de puntos válida."
            )
        
        image_field = self.parameterAsString(parameters, self.IMAGE_FIELD, context)
        chart_folder = self.parameterAsString(parameters, self.CHART_FOLDER, context)
        
        # Verificar que existe el campo de imagen
        field_names = [f.name() for f in source.fields()]
        if image_field not in field_names:
            raise QgsProcessingException(
                f"El campo '{image_field}' no existe en la capa de entrada. "
                f"Campos disponibles: {', '.join(field_names)}"
            )
        
        # Obtener API key
        api_key = self.get_stored_api_key()
        
        if not api_key:
            api_key = PlantNetApiConfigurator.setup_credentials()
        
        if not api_key:
            raise QgsProcessingException(
                "Se requiere una API Key válida de Pl@ntNet para continuar. "
                "Obtenga una en https://my.plantnet.org/"
            )
        
        # Guardar para usos futuros
        self.save_api_key(api_key)
        feedback.pushInfo("✓ API key configurada correctamente.")
        
        # Crear carpeta para gráficos
        if not chart_folder:
            chart_folder = os.path.join(tempfile.gettempdir(), "plantnet_disease_charts")
        
        if not os.path.exists(chart_folder):
            os.makedirs(chart_folder)
        
        feedback.pushInfo(f"✓ Guardando gráficos en: {chart_folder}")
        
        # Crear campos de salida
        fields = QgsFields()
        fields.append(QgsField("ID", QVariant.Int))
        fields.append(QgsField("image", QVariant.String))
        
        # Campos para las 5 enfermedades más probables (solo nombre y score)
        for i in range(1, 6):
            fields.append(QgsField(f"disease_{i}", QVariant.String))  # Nombre común
            fields.append(QgsField(f"sc_{i}", QVariant.Double))       # Score
        
        fields.append(QgsField("others", QVariant.Double))
        fields.append(QgsField("chart", QVariant.String))
        fields.append(QgsField("total_diseases", QVariant.Int))
        
        # Sink de salida
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            source.wkbType(),
            source.sourceCrs()
        )
        
        # Procesar cada feature
        url = "https://my-api.plantnet.org/v2/diseases/identify"
        total = source.featureCount()
        
        feedback.pushInfo(f"Procesando {total} puntos...")
        
        processed = 0
        errors = 0
        
        for idx, feat in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break
            
            feedback.setProgress(int((idx / total) * 100))
            
            # Obtener ruta de imagen
            image_path = feat.attribute(image_field)
            
            if not image_path or not str(image_path).strip():
                feedback.pushWarning(f"Feature {idx}: Campo de imagen vacío")
                errors += 1
                continue
            
            image_path = str(image_path).strip()
            
            if not os.path.exists(image_path):
                feedback.pushWarning(f"Feature {idx}: Imagen no encontrada: {image_path}")
                errors += 1
                continue
            
            # Llamar a la API de PlantNet Disease
            try:
                with open(image_path, "rb") as img_file:
                    files = {"images": img_file}
                    params = {
                        "api-key": api_key,
                        "include-related-images": "false"
                    }
                    
                    response = requests.post(url, files=files, params=params, timeout=60)
                    
                    # Debug
                    feedback.pushInfo(f"Feature {idx}: HTTP {response.status_code}")
                    
                    try:
                        result_data = response.json()
                        feedback.pushInfo(f"Response keys: {list(result_data.keys())}")
                        if "results" in result_data:
                            feedback.pushInfo(f"Results count: {len(result_data['results'])}")
                    except:
                        feedback.pushWarning(f"Feature {idx}: No se pudo parsear JSON")
                        feedback.pushInfo(f"Response: {response.text[:500]}")
                        errors += 1
                        continue
                    
                    if response.status_code == 404:
                        feedback.pushWarning(
                            f"Feature {idx}: No se detectaron enfermedades "
                            "(puede estar sana o no está en la base de datos)"
                        )
                        errors += 1
                        continue
                    elif response.status_code != 200:
                        error_msg = result_data.get("message", str(response.status_code))
                        feedback.pushWarning(f"Feature {idx}: Error API: {error_msg}")
                        errors += 1
                        continue
                    
            except requests.exceptions.RequestException as e:
                feedback.pushWarning(f"Feature {idx}: Error conexión: {str(e)}")
                errors += 1
                continue
            except Exception as e:
                feedback.pushWarning(f"Feature {idx}: Error: {str(e)}")
                import traceback
                feedback.pushInfo(traceback.format_exc())
                errors += 1
                continue
            
            # Extraer resultados
            results = result_data.get("results", [])
            
            if results:
                feedback.pushInfo(f"First result: {list(results[0].keys())}")
            
            # Preparar datos
            diseases = []
            eppo_codes = []
            scores = []
            urls = []
            
            for i in range(5):
                if i < len(results):
                    res = results[i]
                    
                    eppo_code = res.get("name", "")
                    score_val = float(res.get("score", 0.0))
                    
                    # Traducir código EPPO a nombre común
                    disease_name = self.get_disease_name(eppo_code)
                    
                    # Si no hay traducción, usar el código
                    if not disease_name:
                        disease_name = eppo_code
                    
                    diseases.append(disease_name)
                    eppo_codes.append(eppo_code)
                    scores.append(score_val)
                    
                    # URL EPPO
                    if eppo_code:
                        url_info = f"https://gd.eppo.int/taxon/{eppo_code}"
                    else:
                        url_info = ""
                    urls.append(url_info)
                else:
                    diseases.append("")
                    eppo_codes.append("")
                    scores.append(0.0)
                    urls.append("")
            
            # Calcular others
            total_score = sum(scores)
            others = max(0.0, 1.0 - total_score)
            
            # Generar gráfico de dona
            chart_filename = f"disease_chart_{idx}.jpg"
            chart_path = os.path.join(chart_folder, chart_filename)
            self.generate_disease_donut_chart(image_path, diseases, scores, eppo_codes, chart_path)
            
            # Crear feature de salida
            out_feat = QgsFeature(fields)
            out_feat.setGeometry(feat.geometry())
            
            # Preparar atributos
            vals = [idx, image_path]
            
            # Añadir información de cada enfermedad (solo nombre y score)
            for d, s in zip(diseases, scores):
                vals.extend([d, s])
            
            # Estadísticas
            vals.append(others)
            vals.append(chart_path)
            vals.append(len([s for s in scores if s > 0]))
            
            out_feat.setAttributes(vals)
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)
            
            processed += 1
            
            if diseases[0]:
                feedback.pushInfo(
                    f"✓ Feature {idx}: {diseases[0]} ({scores[0]*100:.1f}%)"
                )
            else:
                feedback.pushInfo(f"○ Feature {idx}: No detectado")
        
        # Resumen
        feedback.pushInfo("")
        feedback.pushInfo("=" * 50)
        feedback.pushInfo(f"Procesamiento completado:")
        feedback.pushInfo(f"  - Exitosos: {processed}")
        feedback.pushInfo(f"  - Errores: {errors}")
        feedback.pushInfo(f"  - Total: {total}")
        feedback.pushInfo("=" * 50)
        
        self.dest_id = dest_id
        return {self.OUTPUT: dest_id}

    def postProcessAlgorithm(self, context, feedback):
        """Configurar formulario"""
        
        layer = QgsProcessingContext.takeResultLayer(context, self.dest_id)
        
        if layer:
            self.configure_form(layer)
            feedback.pushInfo("✓ Formulario configurado")
            QgsProject.instance().addMapLayer(layer)
        
        return {self.OUTPUT: self.dest_id}

    def configure_form(self, layer):
        """Configura formulario con pestañas (igual que especies)"""
        
        # Configurar widget de imagen
        img_idx = layer.fields().indexOf("image")
        if img_idx >= 0:
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
            layer.setEditorWidgetSetup(img_idx, setup)
        
        # Configurar widget de gráfico
        chart_idx = layer.fields().indexOf("chart")
        if chart_idx >= 0:
            chart_config = {
                'DocumentViewer': 1,
                'DocumentViewerHeight': 520,
                'DocumentViewerWidth': 700,
                'FileWidget': False,
                'FileWidgetButton': False,
                'FileWidgetFilter': 'Images (*.jpg *.jpeg *.png)',
                'RelativeStorage': 0,
                'StorageMode': 0,
                'UseLink': False,
                'FullUrl': False
            }
            setup = QgsEditorWidgetSetup('ExternalResource', chart_config)
            layer.setEditorWidgetSetup(chart_idx, setup)
        
        # Layout con pestañas
        config = layer.editFormConfig()
        config.setLayout(QgsEditFormConfig.TabLayout)
        
        root = config.invisibleRootContainer()
        root.clear()
        
        # PESTAÑA 1: DATOS
        tab_data = QgsAttributeEditorContainer("Datos", root)
        tab_data.setIsGroupBox(False)
        
        id_group = QgsAttributeEditorContainer("Identificación", tab_data)
        id_group.setIsGroupBox(True)
        
        for field_name in ["ID", "image", "total_diseases"]:
            idx = layer.fields().indexOf(field_name)
            if idx >= 0:
                id_group.addChildElement(QgsAttributeEditorField(field_name, idx, id_group))
        
        tab_data.addChildElement(id_group)
        
        # Resultados
        results_group = QgsAttributeEditorContainer("Enfermedades Detectadas", tab_data)
        results_group.setIsGroupBox(True)
        
        for i in range(1, 6):
            # Solo disease y score (sin eppo ni url)
            for suffix in ["disease", "sc"]:
                field_name = f"{suffix}_{i}"
                idx = layer.fields().indexOf(field_name)
                if idx >= 0:
                    results_group.addChildElement(QgsAttributeEditorField(field_name, idx, results_group))
        
        others_idx = layer.fields().indexOf("others")
        if others_idx >= 0:
            results_group.addChildElement(QgsAttributeEditorField("others", others_idx, results_group))
        
        tab_data.addChildElement(results_group)
        
        # PESTAÑA 2: IMAGEN
        tab_image = QgsAttributeEditorContainer("Imagen", root)
        tab_image.setIsGroupBox(False)
        
        if img_idx >= 0:
            tab_image.addChildElement(QgsAttributeEditorField("image", img_idx, tab_image))
        
        # PESTAÑA 3: GRÁFICO
        tab_chart = QgsAttributeEditorContainer("Gráfico", root)
        tab_chart.setIsGroupBox(False)
        
        if chart_idx >= 0:
            tab_chart.addChildElement(QgsAttributeEditorField("chart", chart_idx, tab_chart))
        
        root.addChildElement(tab_data)
        root.addChildElement(tab_image)
        root.addChildElement(tab_chart)
        
        layer.setEditFormConfig(config)

    def createInstance(self):
        return PlantNetDiseaseIdentifier()
    
    def icon(self):
        base_dir = os.path.dirname(__file__)
        icon_path = os.path.abspath(
        os.path.join(base_dir, "..", "Logo", "PNDICON.png")
        )
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mIconRaster.svg")