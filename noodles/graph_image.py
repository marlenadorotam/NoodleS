"""Render the graph itself at a fixed print scale, independently of the view."""
import math

from Qt import QtCore, QtGui


DPI = 300
PIXELS_PER_SCENE_UNIT = DPI / 96
MARGIN_PIXELS = round(DPI / 2.54)
MAX_PIXELS = 128_000_000


def render_graph_image(viewer):
    scene = viewer.scene()
    nodes = [item for item in viewer.all_nodes() if item.isVisible()]
    if not nodes:
        raise ValueError('Add a node before exporting an image.')
    roots = set(nodes).union(viewer.all_pipes())
    overlays = [item for item in scene.items() if item.parentItem() is None
                and item not in roots and item.isVisible()]
    proxies = [item for item in nodes if getattr(item, '_proxy_mode', False)]
    viewer.exporting_graph_image = True
    try:
        for item in overlays:
            item.hide()
        for item in proxies:
            item.set_proxy_mode(False)

        content = QtCore.QRectF()
        for item in scene.items():
            if item.isVisible() and item.topLevelItem() in roots:
                content = content.united(item.sceneBoundingRect())
        scale = PIXELS_PER_SCENE_UNIT
        width = math.ceil(content.width() * scale) + 2 * MARGIN_PIXELS
        height = math.ceil(content.height() * scale) + 2 * MARGIN_PIXELS
        if width * height > MAX_PIXELS:
            raise ValueError(f'The graph would require a {width:,} × {height:,} px PNG at 300 dpi. '
                             'Bring widely spaced nodes closer together and try again.')
        image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
        if image.isNull():
            raise ValueError('There is not enough memory to render the graph image.')
        image.setDotsPerMeterX(round(DPI / .0254))
        image.setDotsPerMeterY(round(DPI / .0254))
        image.fill(scene.backgroundBrush().color())
        source = QtCore.QRectF(0, 0, width / scale, height / scale)
        source.moveCenter(content.center())
        painter = QtGui.QPainter(image)
        try:
            painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform)
            scene.render(painter, QtCore.QRectF(image.rect()), source)
        finally:
            painter.end()
        return image
    finally:
        for item in proxies:
            item.set_proxy_mode(True)
        for item in overlays:
            item.show()
        viewer.exporting_graph_image = False


def save_graph_image(viewer, path):
    image = render_graph_image(viewer)
    file = QtCore.QSaveFile(str(path))
    if not file.open(QtCore.QIODevice.WriteOnly):
        raise OSError(file.errorString())
    writer = QtGui.QImageWriter(file, b'png')
    if not writer.write(image):
        file.cancelWriting()
        raise OSError(writer.errorString())
    if not file.commit():
        raise OSError(file.errorString())
