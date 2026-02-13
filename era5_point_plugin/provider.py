from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
import os
from .era5_algorithm import ERA5Algorithm
from .Plantnet.Multiorgan_identification import PlantNetIdentifyMultiOrgan
from .Plantnet.Diseases_identification import PlantNetDiseaseIdentifier

class ERA5Provider(QgsProcessingProvider):

    def __init__(self):
        super().__init__()

    def loadAlgorithms(self):
        self.addAlgorithm(ERA5Algorithm())
        self.addAlgorithm(PlantNetIdentifyMultiOrgan())
        self.addAlgorithm(PlantNetDiseaseIdentifier())

    def id(self):
        return "era5_provider"

    def name(self):
        return "ARH PLUGIN"

    def longName(self):
        return self.name()

    def icon(self):
        """Retorna el icono del provider"""
        icon_path = os.path.join(os.path.dirname(__file__),"Logo", 'icon.png')
        
        # Si existe tu icono personalizado, úsalo
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        
        # Si no, usa un icono de QGIS relacionado con clima/datos
        return QIcon(":/images/themes/default/mIconRaster.svg")
    
    def svgIconPath(self):
        """Ruta al icono SVG (opcional, mejor calidad)"""
        svg_path = os.path.join(os.path.dirname(__file__), 'icon.svg')
        if os.path.exists(svg_path):
            return svg_path
        return ""