from . import resources
from .rasteredition import RasterEditPlugin

def classFactory(iface):
    return RasterEditPlugin(iface)
