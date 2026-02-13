def classFactory(iface):
    """
    Load ERA5PointPlugin class from file era5_point_plugin.
    
    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .era5_point_plugin import ERA5PointPlugin
    return ERA5PointPlugin(iface)