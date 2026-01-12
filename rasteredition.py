from . import resources
from qgis.PyQt.QtCore import QObject, Qt, QSize
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QComboBox, QWidgetAction
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import (Qgis, QgsRasterLayer, QgsRasterDataProvider, 
                      QgsWkbTypes, QgsGeometry, QgsPointXY, QgsRasterBlock, QgsRectangle, QgsProject, QgsRasterFileWriter, QgsRasterPipe)
import numpy as np
from scipy.interpolate import griddata
import logging
import os


def qgis_dtype_to_numpy(qgis_dtype):
    """
    Converte o tipo de dados QGIS/GDAL para o dtype NumPy correspondente.
    """
    dtype_map = {
        Qgis.Byte: np.uint8,
        Qgis.UInt16: np.uint16,
        Qgis.Int16: np.int16,
        Qgis.UInt32: np.uint32,
        Qgis.Int32: np.int32,
        Qgis.Float32: np.float32,
        Qgis.Float64: np.float64,
    }
    # Para QGIS 3.30+, os tipos podem estar em Qgis.DataType
    if hasattr(Qgis, 'DataType'):
        dtype_map.update({
            Qgis.DataType.Byte: np.uint8,
            Qgis.DataType.UInt16: np.uint16,
            Qgis.DataType.Int16: np.int16,
            Qgis.DataType.UInt32: np.uint32,
            Qgis.DataType.Int32: np.int32,
            Qgis.DataType.Float32: np.float32,
            Qgis.DataType.Float64: np.float64,
        })
    return dtype_map.get(qgis_dtype, np.float32)  # fallback para float32

# Configurar o logging
logging.basicConfig(
    level=logging.DEBUG,  # Mostra mensagens DEBUG e superiores
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Adicionar handler para a consola
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logging.getLogger().addHandler(console_handler)


class RasterEditTool(QgsMapTool):
    def __init__(self, canvas, callback, iface):
        super().__init__(canvas)
        self.canvas = canvas
        self.callback = callback
        self.iface = iface
        self.rubberBand = None
        self.isDrawing = False
        self.points = []

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.isDrawing:
                if self.rubberBand:
                    self.canvas.scene().removeItem(self.rubberBand)
                    self.rubberBand = None
                self.points = []
                self.isDrawing = False
                self.iface.messageBar().pushMessage(
                    "Edit Canceled",
                    "Drawing operation canceled.",
                    level=Qgis.Info
                )

    def clearPreviousRubberBands(self):
        try:
            if self.rubberBand:
                self.canvas.scene().removeItem(self.rubberBand)
                self.rubberBand = None
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Warning",
                f"Error clearing previous drawing: {str(e)}",
                level=Qgis.Warning
            )

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self.isDrawing:
                self.isDrawing = True
                self.points = []
                if not self.rubberBand:
                    self.rubberBand = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
                    self.rubberBand.setColor(QColor(255, 0, 0, 100))
                    self.rubberBand.setWidth(1)
            point = self.toMapCoordinates(event.pos())
            self.points.append(point)
            self.updateRubberBand()
        elif event.button() == Qt.RightButton and self.isDrawing:
            self.finishDrawing()
    def canvasMoveEvent(self, event):
        if self.isDrawing and self.rubberBand:
            point = self.toMapCoordinates(event.pos())
            temp_points = self.points + [point]
            if len(temp_points) >= 2:
                try:
                    self.rubberBand.setToGeometry(
                        QgsGeometry.fromPolygonXY([temp_points])
                    )
                except Exception:
                    pass

    def updateRubberBand(self):
        if len(self.points) >= 2:
            try:
                self.rubberBand.setToGeometry(
                    QgsGeometry.fromPolygonXY([self.points])
                )
            except Exception:
                self.iface.messageBar().pushMessage(
                    "Warning",
                    "Error updating polygon preview.",
                    level=Qgis.Warning
                )

    def finishDrawing(self):
        if self.isDrawing and len(self.points) >= 3:
            self.points.append(self.points[0])
            geometry = QgsGeometry.fromPolygonXY([self.points])
            if not geometry.isGeosValid():
                geometry = geometry.makeValid()

            if geometry.isGeosValid():
                self.callback(geometry.boundingBox(), self.points)
            else:
                self.iface.messageBar().pushMessage(
                    "Warning",
                    "Invalid polygon geometry. Please try again.",
                    level=Qgis.Warning
                )
            self.canvas.scene().removeItem(self.rubberBand)
            self.rubberBand = None
            self.points = []
        elif self.isDrawing:
            self.iface.messageBar().pushMessage(
                "Warning",
                "Need at least 3 points to create a polygon.",
                level=Qgis.Warning
            )
        self.isDrawing = False

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.finishDrawing()

class RasterEditPlugin(QObject):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.undoStack = []
        self.redoStack = []  # Novo stack para REDO
        self.suppress_tool = None
        self.interpolate_tool = None
        self.setupActions()


    def redo_last_edit(self):
        logging.debug("Iniciando a função redo_last_edit...")
        
        # Verificar se há edições para refazer
        if not self.redoStack:
            logging.warning("O redoStack está vazio. Não há edições para refazer.")
            self.iface.messageBar().pushMessage(
                "Warning", "No edits to redo.",
                level=Qgis.Warning
            )
            return
            
        last_state = self.redoStack.pop()
        logging.debug(f"Estado recuperado do redoStack: {last_state}")
        
        # Obter a camada raster ativa
        raster_layer = self.iface.activeLayer()
        if not isinstance(raster_layer, QgsRasterLayer):
            logging.error("A camada ativa não é um raster. Operação cancelada.")
            self.iface.messageBar().pushMessage(
                "Error", "Active layer is not a raster.",
                level=Qgis.Critical
            )
            return
            
        provider = raster_layer.dataProvider()
        
        try:
            # Tornar a camada editável
            logging.debug("Tornando o raster editável...")
            provider.setEditable(True)
            
            # Validar integridade do bloco do redoStack
            redo_block = last_state['block']
            if not isinstance(redo_block, QgsRasterBlock):
                raise ValueError("Bloco do redoStack não é um QgsRasterBlock válido.")
            if redo_block.isEmpty():
                raise ValueError("Bloco do redoStack está vazio.")
                
            # Capturar o estado atual para o undoStack
            logging.debug("Capturando o estado atual para o undoStack...")
            current_extent = QgsRectangle(
                raster_layer.extent().xMinimum() + last_state['x_min'] * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - (last_state['y_min'] + last_state['n_rows']) * raster_layer.rasterUnitsPerPixelY(),
                raster_layer.extent().xMinimum() + (last_state['x_min'] + last_state['n_cols']) * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - last_state['y_min'] * raster_layer.rasterUnitsPerPixelY()
            )
            
            logging.debug(f"Extensão calculada: {current_extent.toString()}")
            
            current_block = provider.block(
                1,
                current_extent,
                last_state['n_cols'],
                last_state['n_rows']
            )
            
            if current_block.isEmpty():
                raise ValueError("Falha ao capturar o estado atual para o undoStack.")
                
            # Validar consistência do bloco capturado
            if (current_block.width() != last_state['n_cols'] or
                current_block.height() != last_state['n_rows']):
                raise ValueError("Dimensões do bloco atual não correspondem ao estado salvo.")
                
            logging.debug(f"Bloco capturado para o undoStack: {current_block.width()}x{current_block.height()}")
            
            undo_state = {
                'block': QgsRasterBlock(current_block.dataType(),
                                      current_block.width(),
                                      current_block.height()),
                'x_min': last_state['x_min'],
                'y_min': last_state['y_min'],
                'n_cols': last_state['n_cols'],
                'n_rows': last_state['n_rows'],
                'data_type': last_state['data_type']
            }
            
            undo_state['block'].setData(current_block.data())
            logging.debug(f"Estado capturado para o undoStack (dados): {undo_state}")
            
            # Adicionar ao undoStack
            self.undoStack.append(undo_state)
            
            # Aplicar o bloco do redoStack
            logging.debug("Escrevendo o bloco do redoStack no raster...")
            success = provider.writeBlock(
                redo_block, 1,
                last_state['x_min'],
                last_state['y_min']
            )
            
            if not success:
                raise ValueError("Falha ao escrever o bloco do redoStack no raster.")
                
            logging.debug("Bloco escrito com sucesso no raster.")
            
            provider.setEditable(False)
            raster_layer.triggerRepaint()
            logging.debug("Repaint do raster acionado.")
            
            # Habilitar a ação UNDO
            self.undo_action.setEnabled(True)
            
        except Exception as e:
            provider.setEditable(False)
            logging.error(f"Erro durante o REDO: {str(e)}", exc_info=True)
            self.iface.messageBar().pushMessage(
                "Error", f"Erro durante o REDO: {str(e)}",
                level=Qgis.Critical
            )
            
        # Desabilitar REDO se o redoStack estiver vazio
        if not self.redoStack:
            logging.debug("O redoStack está agora vazio. Desabilitando a ação REDO.")
            self.redo_action.setEnabled(False)

    def setupActions(self):
        # Criar todas as ações primeiro
        self.suppress_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/suppress.png'),
            'Suppress Raster Values',
            self.iface.mainWindow()
        )
        self.suppress_action.triggered.connect(self.activate_suppress_tool)
    
        self.interpolate_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/interpolate.png'),
            'Interpolate NoData Values',
            self.iface.mainWindow()
        )
        self.interpolate_action.triggered.connect(self.activate_interpolate_tool)
    
        self.interpolate_all_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/interpolate_all.png'),
            'Interpolate All Values in Area',
            self.iface.mainWindow()
        )
        self.interpolate_all_action.triggered.connect(self.activate_interpolate_all_tool)
    
        self.save_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/save.png'),
            'Create Editable Copy',
            self.iface.mainWindow()
        )
        self.save_action.triggered.connect(self.create_editable_copy)
    
        self.undo_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/undo.png'),
            'Undo Last Edit',
            self.iface.mainWindow()
        )
        self.undo_action.triggered.connect(self.undo_last_edit)
        self.undo_action.setEnabled(False)
    
        
        self.redo_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/redo.png'),
            'Redo Last Edit',
            self.iface.mainWindow()
         )
        self.redo_action.triggered.connect(self.redo_last_edit)
        self.redo_action.setEnabled(False)
        
        self.activate_edit_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/activate.png'),
            'Activate Edit',
            self.iface.mainWindow()
         )
        self.activate_edit_action.triggered.connect(self.activate_tool)
        self.activate_edit_action.setEnabled(False)
        
        self.deactivate_edit_action = QAction(
            QIcon(':/plugins/RasterEditPlugin/icons/deactivate.png'),
            'Deactivate Edit',
            self.iface.mainWindow()
         )
        self.deactivate_edit_action.triggered.connect(self.deactivate_tool)
        self.deactivate_edit_action.setEnabled(False)
    
        # Criar ComboBox para métodos de interpolação
        self.method_combo = QComboBox()
        self.method_combo.addItems(['linear', 'cubic', 'nearest'])
        self.method_combo.setToolTip('Select interpolation method')
        
        # Adicionar o ComboBox à toolbar
        self.method_action = QWidgetAction(self.iface.mainWindow())
        self.method_action.setDefaultWidget(self.method_combo)
    
        # Configurar estados iniciais
        self.suppress_action.setEnabled(False)
        self.interpolate_action.setEnabled(False)
        self.interpolate_all_action.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.save_action.setEnabled(False)  # Alterado: inicia desabilitado
        self.activate_edit_action.setEnabled(True)  # Único botão ativo inicialmente
        self.deactivate_edit_action.setEnabled(False)

        
        
    def activate_tool(self):
        # Obter a camada raster ativa
        raster_layer = self.iface.activeLayer()
        
        if not raster_layer:
            self.iface.messageBar().pushMessage(
                "Error",
                "Please select a layer.",
                level=Qgis.Warning
            )
            return
            
        if not isinstance(raster_layer, QgsRasterLayer):
            self.iface.messageBar().pushMessage(
                "Error",
                "Please select a raster layer.",
                level=Qgis.Warning
            )
            return
        
        # Verificar se é uma camada editável (_edited)
        if "_edited" in raster_layer.name():
            # Ativar todas as ferramentas diretamente
            provider = raster_layer.dataProvider()
            provider.setEditable(True)
            
            self.suppress_action.setEnabled(True)
            self.interpolate_action.setEnabled(True)
            self.interpolate_all_action.setEnabled(True)
            self.save_action.setEnabled(False)  # Desativa save pois já é editável
            self.activate_edit_action.setEnabled(False)
            self.deactivate_edit_action.setEnabled(True)
            
            self.iface.messageBar().pushMessage(
                "Edit Mode",
                "Editable layer detected. Edit mode activated.",
                level=Qgis.Info
            )
        else:
            # Ativar apenas o botão de save
            self.save_action.setEnabled(True)
            self.activate_edit_action.setEnabled(False)
            self.deactivate_edit_action.setEnabled(True)
            
            self.iface.messageBar().pushMessage(
                "Edit Mode",
                "Create an editable copy to start editing.",
                level=Qgis.Info
            )

        
    def deactivate_tool(self):
        # Restaurar todos os ícones para o estado normal
        self.suppress_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/suppress.png'))
        self.interpolate_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate.png'))
        self.interpolate_all_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate_all.png'))
        
        # Obter a camada raster ativa
        raster_layer = self.iface.activeLayer()
        if not isinstance(raster_layer, QgsRasterLayer):
            return
            
        # Desabilitar edição
        provider = raster_layer.dataProvider()
        if provider.isEditable():
            provider.setEditable(False)
        
        # Desabilitar as ferramentas
        self.suppress_action.setEnabled(False)
        self.interpolate_action.setEnabled(False)
        self.interpolate_all_action.setEnabled(False)
        
        # Atualizar estado dos botões
        self.activate_edit_action.setEnabled(True)
        self.deactivate_edit_action.setEnabled(False)
        
        # Limpar as pilhas de undo/redo
        self.undoStack.clear()
        self.redoStack.clear()
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        
        # Ativar a ferramenta Pan do QGIS
        self.iface.actionPan().trigger()
        
        self.iface.messageBar().pushMessage(
            "Edit Mode",
            "Raster edit mode deactivated.",
            level=Qgis.Info
        )



    def activate_suppress_tool(self):
        # Restaurar ícones das outras ferramentas
        self.interpolate_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate.png'))
        self.interpolate_all_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate_all.png'))
        
        # Ativar ícone desta ferramenta
        self.suppress_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/suppress_active.png'))
        self.suppress_tool = RasterEditTool(
            self.canvas,
            lambda rectangle, points: self.suppress_zone(rectangle, points),
            self.iface)
        self.canvas.setMapTool(self.suppress_tool)
        self.iface.messageBar().pushMessage(
            "Raster Edit Tool",
            "Click to add points, right-click to finish, ESC to cancel.",
            level=Qgis.Info
        )


    def create_editable_copy(self):
        raster_layer = self.iface.activeLayer()
        if not isinstance(raster_layer, QgsRasterLayer):
            self.iface.messageBar().pushMessage(
                "Error",
                "Please select a raster layer.",
                level=Qgis.Warning
            )
            return
    
        # Criar nome e caminho da cópia
        original_path = raster_layer.source()
        original_dir = os.path.dirname(original_path)
        original_name = os.path.basename(original_path)
        name, ext = os.path.splitext(original_name)
        new_name = f"{name}_edited{ext}"
        new_path = os.path.join(original_dir, new_name)
    
        try:
            # Criar cópia usando QgsRasterFileWriter
            writer = QgsRasterFileWriter(new_path)
            pipe = QgsRasterPipe()
            provider = raster_layer.dataProvider()
            
            if not pipe.set(provider.clone()):
                raise ValueError("Cannot set pipe provider")
                
            success = writer.writeRaster(
                pipe,
                provider.xSize(),
                provider.ySize(),
                provider.extent(),
                provider.crs()
            )
    
            if success == 0:  # QgsRasterFileWriter retorna 0 para sucesso
                # Carregar nova camada
                new_layer = QgsRasterLayer(new_path, f"{raster_layer.name()}_edited")
                if new_layer.isValid():
                    QgsProject.instance().addMapLayer(new_layer)
                    self.iface.setActiveLayer(new_layer)
                    
                    # Habilitar outras ações
                    self.suppress_action.setEnabled(True)
                    self.interpolate_action.setEnabled(True)
                    self.interpolate_all_action.setEnabled(True)
                    
                    self.iface.messageBar().pushMessage(
                        "Success",
                        "Editable copy created and activated.",
                        level=Qgis.Success
                    )
                else:
                    raise ValueError("Failed to load new layer")
            else:
                raise ValueError("Failed to write raster")
    
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Error",
                f"Error creating copy: {str(e)}",
                level=Qgis.Critical
            )

    def suppress_zone(self, rectangle, points):
        raster_layer = self.iface.activeLayer()
        if not isinstance(raster_layer, QgsRasterLayer):
            self.iface.messageBar().pushMessage(
                "Error",
                "Please select a raster layer.",
                level=Qgis.Warning
            )
            return
    
        provider = raster_layer.dataProvider()
        try:
            provider.setEditable(True)
            no_data_value = provider.sourceNoDataValue(1)
    
            # Calcular limites do bloco
            x_min, y_min, x_max, y_max = self.calculate_bounds(rectangle, provider.xSize(), provider.ySize(), raster_layer)
    
            # Obter o bloco do raster
            block_extent = QgsRectangle(
                raster_layer.extent().xMinimum() + x_min * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - y_max * raster_layer.rasterUnitsPerPixelY() - raster_layer.rasterUnitsPerPixelY(),
                raster_layer.extent().xMinimum() + (x_max + raster_layer.rasterUnitsPerPixelX()) * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - y_min * raster_layer.rasterUnitsPerPixelY()
            )
            logging.debug(f"Block extent: {block_extent}")
    
            input_block = provider.block(1,  # número da banda
                                       block_extent,  # QgsRectangle com a extensão
                                       int(x_max - x_min + 1),  # largura
                                       int(y_max - y_min + 1))  # altura
            if not input_block:
                raise ValueError("Failed to retrieve raster block.")
            self.save_state(raster_layer, x_min, y_min, input_block)
    
            # Detectar o dtype correto do raster
            native_dtype = qgis_dtype_to_numpy(provider.dataType(1))
            array = np.frombuffer(input_block.data(), dtype=native_dtype).reshape((y_max - y_min + 1, x_max - x_min + 1))
            # Guardar tipo original e converter para float64 para operações
            original_dtype = array.dtype
            array = array.astype(np.float64)
    
            # Aplicar NoData à área especificada
            if points:
                polygon = QgsGeometry.fromPolygonXY([points])
                mask = np.zeros(array.shape, dtype=bool)
                for y in range(array.shape[0]):
                    for x in range(array.shape[1]):
                        map_x = block_extent.xMinimum() + x * raster_layer.rasterUnitsPerPixelX()
                        map_y = block_extent.yMaximum() - y * raster_layer.rasterUnitsPerPixelY()
                        if polygon.contains(QgsPointXY(map_x, map_y)):
                            mask[y, x] = True
                array[mask] = no_data_value
            else:
                array.fill(no_data_value)
    
            # Criar e gravar o bloco atualizado - converter de volta ao tipo original
            output_block = QgsRasterBlock(provider.dataType(1), x_max - x_min + 1, y_max - y_min + 1)
            output_block.setData(array.astype(original_dtype).tobytes())
            success = provider.writeBlock(output_block, 1, x_min, y_min)
            if not success:
                raise ValueError("Failed to write raster block.")
    
            provider.setEditable(False)
            raster_layer.triggerRepaint()
            self.iface.messageBar().pushMessage(
                "Suppress Completed",
                "Selected area replaced with NoData.",
                level=Qgis.Success
            )
    
        except Exception as e:
            provider.setEditable(False)
            logging.error(f"Error during suppression: {str(e)}")
            self.iface.messageBar().pushMessage(
                "Error",
                f"Error during suppression: {str(e)}",
                level=Qgis.Critical
            )


    def activate_interpolate_tool(self):
        # Restaurar ícones das outras ferramentas
        self.suppress_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/suppress.png'))
        self.interpolate_all_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate_all.png'))
        
        # Ativar ícone desta ferramenta
        self.interpolate_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate_active.png'))
        self.interpolate_tool = RasterEditTool(
            self.canvas,
            lambda rectangle, points: self.interpolate_zone(rectangle, points),
            self.iface)
        self.canvas.setMapTool(self.interpolate_tool)
        self.iface.messageBar().pushMessage(
            "Raster Edit Tool",
            "Click to add points, right-click to finish, ESC to cancel.",
            level=Qgis.Info
        )

    def interpolate_zone(self, rectangle, points):
        raster_layer = self.iface.activeLayer()
        if not isinstance(raster_layer, QgsRasterLayer):
            self.iface.messageBar().pushMessage(
                "Error",
                "Please select a raster layer.",
                level=Qgis.Warning
            )
            return
    
        provider = raster_layer.dataProvider()
        try:
            provider.setEditable(True)
            no_data_value = provider.sourceNoDataValue(1)
    
            # Calcular limites do bloco
            x_min, y_min, x_max, y_max = self.calculate_bounds(rectangle, provider.xSize(), provider.ySize(), raster_layer)
            
            # Obter o bloco do raster
            block_extent = QgsRectangle(
                raster_layer.extent().xMinimum() + x_min * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - y_max * raster_layer.rasterUnitsPerPixelY() - raster_layer.rasterUnitsPerPixelY(),
                raster_layer.extent().xMinimum() + (x_max + raster_layer.rasterUnitsPerPixelX()) * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - y_min * raster_layer.rasterUnitsPerPixelY()
            )
    
            input_block = provider.block(1,
                                       block_extent,
                                       int(x_max - x_min + 1),
                                       int(y_max - y_min + 1))
    
            # Detectar o dtype correto do raster
            native_dtype = qgis_dtype_to_numpy(provider.dataType(1))
            array = np.frombuffer(input_block.data(), dtype=native_dtype).reshape((y_max - y_min + 1, x_max - x_min + 1))
            # Guardar tipo original e converter para float64 para operações de interpolação
            original_dtype = array.dtype
            array = array.astype(np.float64)
            
            # Criar máscara do polígono de forma vetorizada
            polygon = QgsGeometry.fromPolygonXY([points])
            y_coords, x_coords = np.meshgrid(
                np.linspace(block_extent.yMaximum(), block_extent.yMinimum(), array.shape[0]),
                np.linspace(block_extent.xMinimum(), block_extent.xMaximum(), array.shape[1]),
                indexing='ij'
            )
            
            points = [QgsPointXY(x, y) for x, y in zip(x_coords.flatten(), y_coords.flatten())]
            mask = np.array([polygon.contains(p) for p in points]).reshape(array.shape)
            
            # Identificar pontos válidos na borda
            nodata_mask = array == no_data_value
            valid_mask = ~nodata_mask & ~mask
            
            # Interpolar apenas os pontos necessários
            valid_points = np.column_stack((x_coords[valid_mask], y_coords[valid_mask]))
            valid_values = array[valid_mask]
            
            # Pontos a serem interpolados
            interp_mask = mask & nodata_mask
            if np.any(interp_mask):
                points_to_interpolate = np.column_stack((x_coords[interp_mask], y_coords[interp_mask]))
                
                interpolated = griddata(
                    valid_points,
                    valid_values,
                    points_to_interpolate,
                    method=self.method_combo.currentText(),  # Usar método selecionado
                    fill_value=no_data_value
                )
                
                array[interp_mask] = interpolated
    
            # Converter de volta ao tipo original antes de escrever
            output_block = QgsRasterBlock(provider.dataType(1), x_max - x_min + 1, y_max - y_min + 1)
            output_block.setData(array.astype(original_dtype).tobytes())
            success = provider.writeBlock(output_block, 1, x_min, y_min)
            if not success:
                raise ValueError("Failed to write raster block.")
    
            provider.setEditable(False)
            raster_layer.triggerRepaint()
            self.iface.messageBar().pushMessage(
                "Interpolation Completed",
                "Raster values interpolated successfully.",
                level=Qgis.Success
            )
    
        except Exception as e:
            provider.setEditable(False)
            logging.error(f"Error during interpolation: {str(e)}")
            self.iface.messageBar().pushMessage(
                "Error",
                f"Error during interpolation: {str(e)}",
                level=Qgis.Critical
            )

    def activate_interpolate_all_tool(self):
        # Restaurar ícones das outras ferramentas
        self.suppress_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/suppress.png'))
        self.interpolate_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate.png'))
        
        # Ativar ícone desta ferramenta
        self.interpolate_all_action.setIcon(QIcon(':/plugins/RasterEditPlugin/icons/interpolate_all_active.png'))
        self.interpolate_all_tool = RasterEditTool(
            self.canvas,
            lambda rectangle, points: self.interpolate_all_zone(rectangle, points),
            self.iface)
        self.canvas.setMapTool(self.interpolate_all_tool)
        self.iface.messageBar().pushMessage(
            "Raster Edit Tool",
            "Click to add points, right-click to finish, ESC to cancel.",
            level=Qgis.Info
        )
        
    def interpolate_all_zone(self, rectangle, points):
        raster_layer = self.iface.activeLayer()
        if not isinstance(raster_layer, QgsRasterLayer):
            self.iface.messageBar().pushMessage(
                "Error",
                "Please select a raster layer.",
                level=Qgis.Warning
            )
            return
    
        provider = raster_layer.dataProvider()
        try:
            provider.setEditable(True)
            no_data_value = provider.sourceNoDataValue(1)
    
            # Calcular limites do bloco
            x_min, y_min , x_max, y_max = self.calculate_bounds(rectangle, provider.xSize(), provider.ySize(), raster_layer)
            
            # Obter o bloco do raster
            block_extent = QgsRectangle(
                raster_layer.extent().xMinimum() + x_min * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - y_max * raster_layer.rasterUnitsPerPixelY() - raster_layer.rasterUnitsPerPixelY(),  # subtraindo um pixel extra
                raster_layer.extent().xMinimum() + (x_max + raster_layer.rasterUnitsPerPixelX()) * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - y_min * raster_layer.rasterUnitsPerPixelY()
            )
    
            input_block = provider.block(1, block_extent, int(x_max - x_min + 1), int(y_max - y_min + 1))
            if not input_block:
                raise ValueError("Failed to retrieve raster block.")
            self.save_state(raster_layer, x_min, y_min, input_block)
    
            # Detectar o dtype correto do raster
            native_dtype = qgis_dtype_to_numpy(provider.dataType(1))
            array = np.frombuffer(input_block.data(), dtype=native_dtype).reshape((y_max - y_min +1, x_max - x_min +1))
            # Guardar tipo original e converter para float64 para operações de interpolação
            original_dtype = array.dtype
            array = array.astype(np.float64)
            
            # Criar máscara do polígono de forma vetorizada
            polygon = QgsGeometry.fromPolygonXY([points])
            y_coords, x_coords = np.meshgrid(
                np.linspace(block_extent.yMaximum(), block_extent.yMinimum(), array.shape[0]),
                np.linspace(block_extent.xMinimum(), block_extent.xMaximum(), array.shape[1]),
                indexing='ij'
            )
            
            points = [QgsPointXY(x, y) for x, y in zip(x_coords.flatten(), y_coords.flatten())]
            mask = np.array([polygon.contains(p) for p in points]).reshape(array.shape)
            
            # Identificar pontos válidos fora do polígono
            valid_mask = ~mask
            valid_points = np.column_stack((x_coords[valid_mask], y_coords[valid_mask]))
            valid_values = array[valid_mask]
            
            # Interpolar todos os pontos dentro do polígono
            points_to_interpolate = np.column_stack((x_coords[mask], y_coords[mask]))
            interpolated = griddata(
                valid_points,
                valid_values,
                points_to_interpolate,
                method=self.method_combo.currentText(),  # Usar método selecionado
                fill_value=no_data_value
            )
            
            array[mask] = interpolated
    
            # Converter de volta ao tipo original antes de escrever
            output_block = QgsRasterBlock(provider.dataType(1), x_max - x_min + 1, y_max - y_min + 1)
            output_block.setData(array.astype(original_dtype).tobytes())
            success = provider.writeBlock(output_block, 1, x_min , y_min)
            if not success:
                raise ValueError("Failed to write raster block.")
    
            provider.setEditable(False)
            raster_layer.triggerRepaint()
            self.iface.messageBar().pushMessage(
                "Interpolation Completed",
                "All values in selected area interpolated successfully.",
                level=Qgis.Success
            )
    
        except Exception as e:
            provider.setEditable(False)
            logging.error(f"Error during interpolation: {str(e)}")
            self.iface.messageBar().pushMessage(
                "Error",
                f"Error during interpolation: {str(e)}",
                level=Qgis.Critical
            )
        
    def calculate_bounds(self, rectangle, cols, rows, raster_layer):
        # Convert map coordinates to pixel coordinates
        x_min = int((rectangle.xMinimum() - raster_layer.extent().xMinimum()) / raster_layer.rasterUnitsPerPixelX()) 
        y_min = int((raster_layer.extent().yMaximum() - rectangle.yMaximum()) / raster_layer.rasterUnitsPerPixelY()) 
        x_max = int((rectangle.xMaximum() - raster_layer.extent().xMinimum()) / raster_layer.rasterUnitsPerPixelX())
        y_max = int((raster_layer.extent().yMaximum() - rectangle.yMinimum()) / raster_layer.rasterUnitsPerPixelY())
        
        # Ensure bounds are within raster dimensions
        x_min = max(0, min(x_min, cols - 1))
        y_min = max(0, min(y_min, rows - 1))
        x_max = max(0, min(x_max, cols - 1))
        y_max = max(0, min(y_max, rows - 1))
        
        return x_min, y_min, x_max, y_max


    def save_changes(self):
        raster_layer = self.iface.activeLayer()
        if isinstance(raster_layer, QgsRasterLayer):
            try:
                provider = raster_layer.dataProvider()
                if provider.isEditable():
                    provider.setEditable(False)
                    provider.commitChanges()  # Adicionar esta linha
                    raster_layer.triggerRepaint()
                    self.iface.messageBar().pushMessage(
                        "Save Changes",
                        "Raster saved successfully.",
                        level=Qgis.Success
                    )
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    "Error",
                    f"Error saving changes: {str(e)}",
                    level=Qgis.Critical
                )
                
    def initGui(self):
        # Criar toolbar dedicada
        self.toolbar = self.iface.addToolBar('Raster Edit')
        self.toolbar.setIconSize(self.iface.iconSize())  # Define o tamanho dos ícones
        self.toolbar.setObjectName('RasterEditToolbar')
        
        # Remover os addToolBarIcon individuais e usar addAction na toolbar
        self.toolbar.addAction(self.save_action) # Create Editable Copy primeiro
        self.toolbar.addAction(self.suppress_action)
        self.toolbar.addAction(self.interpolate_action)
        self.toolbar.addAction(self.interpolate_all_action)
        self.toolbar.addAction(self.method_action)
        self.toolbar.addAction(self.undo_action)
        self.toolbar.addAction(self.redo_action)
        self.toolbar.addAction(self.activate_edit_action)
        self.toolbar.addAction(self.deactivate_edit_action)
        
        
        # Adicionar ao menu
        self.iface.addPluginToMenu('&Raster Edit', self.save_action)
        self.iface.addPluginToMenu('&Raster Edit', self.suppress_action)
        self.iface.addPluginToMenu('&Raster Edit', self.interpolate_action)
        self.iface.addPluginToMenu('&Raster Edit', self.interpolate_all_action)
        self.iface.addPluginToMenu('&Raster Edit', self.undo_action)
        self.iface.addPluginToMenu('&Raster Edit', self.redo_action)
        self.iface.addPluginToMenu('&Raster Edit', self.activate_edit_action)
        self.iface.addPluginToMenu('&Raster Edit', self.deactivate_edit_action)

    
    def unload(self):
        self.iface.removeToolBarIcon(self.save_action)
        self.iface.removeToolBarIcon(self.suppress_action)
        self.iface.removeToolBarIcon(self.interpolate_action)
        self.iface.removeToolBarIcon(self.interpolate_all_action)
        self.iface.removeToolBarIcon(self.undo_action)
        self.iface.removeToolBarIcon(self.redo_action)
        self.iface.removeToolBarIcon(self.activate_edit_action)
        self.iface.removeToolBarIcon(self.deactivate_edit_action)  # Corrigido aqui
        
        self.iface.removePluginMenu('&Raster Edit', self.save_action)
        self.iface.removePluginMenu('&Raster Edit', self.suppress_action)
        self.iface.removePluginMenu('&Raster Edit', self.interpolate_action)
        self.iface.removePluginMenu('&Raster Edit', self.interpolate_all_action)
        self.iface.removePluginMenu('&Raster Edit', self.undo_action)
        self.iface.removePluginMenu('&Raster Edit', self.redo_action)
        self.iface.removePluginMenu('&Raster Edit', self.activate_edit_action)
        self.iface.removePluginMenu('&Raster Edit', self.deactivate_edit_action)  # E aqui também
        
        
        if hasattr(self, 'toolbar'):
            del self.toolbar


# Função helper mantida como referência para possíveis usos futuros
# Atualmente não está em uso pois foi substituída por lógica mais precisa no UNDO/REDO
# que preserva escala e posicionamento exatos dos blocos editados


#    def get_current_block(self, provider, x_min, y_min, width, height, transform):
#       """
#        Helper method to get current raster block state with precise positioning
#        """
#        block_extent = QgsRectangle(
#            transform[0] + (x_min * transform[1]),
#            transform[3] + (y_min * transform[5]),
#            transform[0] + ((x_min + width) * transform[1]),
#            transform[3] + ((y_min + height) * transform[5])
#        )
#        
#       block = provider.block(1, block_extent, width, height)
#        if block.isEmpty():
#            return None
#            
#        new_block = QgsRasterBlock(block.dataType(), width, height)
#        new_block.setData(block.data())
#        return new_block



    def save_state(self, raster_layer, x_min, y_min, block):
        """
        Salva o estado do raster usando coordenadas e número exato de linhas/colunas.
        Evita salvar estados redundantes.
        """
        if not isinstance(block, QgsRasterBlock):
            return
        
        # Garantir que temos dados válidos
        if block.isEmpty():
            return
        
        # Criar nova cópia do bloco
        new_block = QgsRasterBlock(block.dataType(), block.width(), block.height())
        new_block.setData(block.data())
    
        # Verificar redundância com o último estado salvo
        if self.undoStack and self.undoStack[-1]['block'].data() == new_block.data():
            # Bloco é idêntico ao último estado, ignorar
            return
    
        # Armazenar novo estado
        state = {
            'block': new_block,
            'x_min': int(x_min),
            'y_min': int(y_min),
            'n_cols': block.width(),
            'n_rows': block.height(),
            'data_type': block.dataType()
        }

        # Atualizar pilhas
        self.redoStack.clear()
        self.redo_action.setEnabled(False)
        self.undoStack.append(state)
        self.undo_action.setEnabled(True)

    
    def undo_last_edit(self):
        logging.debug("Iniciando a função undo_last_edit...")
    
        # Verificar se há edições para desfazer
        if not self.undoStack:
            logging.warning("O undoStack está vazio. Não há edições para desfazer.")
            self.iface.messageBar().pushMessage(
                "Warning", "No edits to undo.",
                level=Qgis.Warning
            )
            return
    
        last_state = self.undoStack.pop()
        logging.debug(f"Estado recuperado do undoStack: {last_state}")
    
        # Obter a camada raster ativa
        raster_layer = self.iface.activeLayer()
        if not isinstance(raster_layer, QgsRasterLayer):
            logging.error("A camada ativa não é um raster. Operação cancelada.")
            self.iface.messageBar().pushMessage(
                "Error", "Active layer is not a raster.",
                level=Qgis.Critical
            )
            return
    
        provider = raster_layer.dataProvider()
    
        try:
            # Tornar a camada editável
            logging.debug("Tornando o raster editável...")
            provider.setEditable(True)
    
            # Validar integridade do bloco do undoStack
            undo_block = last_state['block']
            if not isinstance(undo_block, QgsRasterBlock):
                raise ValueError("Bloco do undoStack não é um QgsRasterBlock válido.")
    
            if undo_block.isEmpty():
                raise ValueError("Bloco do undoStack está vazio.")
    
            # Capturar o estado atual para o redoStack
            logging.debug("Capturando o estado atual para o redoStack...")
            current_extent = QgsRectangle(
                raster_layer.extent().xMinimum() + last_state['x_min'] * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - (last_state['y_min'] + last_state['n_rows']) * raster_layer.rasterUnitsPerPixelY(),
                raster_layer.extent().xMinimum() + (last_state['x_min'] + last_state['n_cols']) * raster_layer.rasterUnitsPerPixelX(),
                raster_layer.extent().yMaximum() - last_state['y_min'] * raster_layer.rasterUnitsPerPixelY()
            )
            logging.debug(f"Extensão calculada: {current_extent.toString()}")
    
            current_block = provider.block(
                1,
                current_extent,
                last_state['n_cols'],
                last_state['n_rows']
            )
            if current_block.isEmpty():
                raise ValueError("Falha ao capturar o estado atual para o redoStack.")
    
            # Validar consistência do bloco capturado
            if (current_block.width() != last_state['n_cols'] or
                    current_block.height() != last_state['n_rows']):
                raise ValueError("Dimensões do bloco atual não correspondem ao estado salvo.")
    
            logging.debug(f"Bloco capturado para o redoStack: {current_block.width()}x{current_block.height()}")
    
            redo_state = {
                'block': QgsRasterBlock(current_block.dataType(),
                                        current_block.width(),
                                        current_block.height()),
                'x_min': last_state['x_min'],
                'y_min': last_state['y_min'],
                'n_cols': last_state['n_cols'],
                'n_rows': last_state['n_rows'],
                'data_type': last_state['data_type']
            }
            redo_state['block'].setData(current_block.data())
            logging.debug(f"Estado capturado para o redoStack (dados): {redo_state}")
    
            # Adicionar ao redoStack
            self.redoStack.append(redo_state)
    
            # Aplicar o bloco do undoStack
            logging.debug("Aplicando o bloco do undoStack ao raster...")
            success = provider.writeBlock(
                undo_block, 1,
                last_state['x_min'],
                last_state['y_min']
            )
            if not success:
                raise ValueError("Falha ao escrever o bloco do undoStack no raster.")
    
            logging.debug("Bloco do undoStack aplicado com sucesso ao raster.")
            provider.setEditable(False)
            raster_layer.triggerRepaint()
            logging.debug("Repaint do raster acionado.")
    
            # Habilitar a ação REDO
            self.redo_action.setEnabled(True)
    
        except Exception as e:
            provider.setEditable(False)
            logging.error(f"Erro durante o UNDO: {str(e)}", exc_info=True)
            self.iface.messageBar().pushMessage(
                "Error", f"Erro durante o UNDO: {str(e)}",
                level=Qgis.Critical
            )
    
        # Desabilitar UNDO se o undoStack estiver vazio
        if not self.undoStack:
            logging.debug("O undoStack está agora vazio. Desabilitando a ação UNDO.")
            self.undo_action.setEnabled(False)
