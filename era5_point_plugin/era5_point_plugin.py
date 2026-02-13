from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication
import os
from .provider import ERA5Provider

class ERA5PointPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.toolbar_action = None

    def initGui(self):
        # Registrar el provider para Processing Toolbox
        self.provider = ERA5Provider()
        QgsApplication.processingRegistry().addProvider(self.provider)
        
        # Crear acción para la toolbar
        icon_path = os.path.join(os.path.dirname(__file__),"Logo", 'icon.png')
        
        # Si no tienes icon.png, usa un icono de QGIS
        if not os.path.exists(icon_path):
            icon_path = ":/images/themes/default/mActionAddBasicShape.svg"
        
        self.toolbar_action = QAction(
            QIcon(icon_path),
            "ERA5-Land Data Extractor",
            self.iface.mainWindow()
        )
        
        self.toolbar_action.setWhatsThis("Extract ERA5-Land climate data")
        self.toolbar_action.setStatusTip("Open ERA5-Land Data Extractor")
        
        # Conectar al método que abre el algoritmo
        self.toolbar_action.triggered.connect(self.run_algorithm)
        
        # Agregar a la toolbar
        self.iface.addToolBarIcon(self.toolbar_action)
        
        # Opcionalmente, agregarlo al menú Plugins
        self.iface.addPluginToMenu("&ASM", self.toolbar_action)

    def unload(self):
        # Remover de Processing
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        
        # Remover de toolbar
        if self.toolbar_action:
            self.iface.removeToolBarIcon(self.toolbar_action)
            self.iface.removePluginMenu("&ASM", self.toolbar_action)
            del self.toolbar_action

    def run_algorithm(self):
        """Abre el algoritmo en el Processing dialog"""
        try:
            from processing import execAlgorithmDialog
            
            # Ejecutar el algoritmo mostrando su diálogo
            execAlgorithmDialog("era5_provider:era5_extractor")
            
        except Exception as e:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Could not open ERA5 algorithm: {str(e)}"
            )