"""Draw model-anchored annotations in the native viewport's painter pass."""
import math

from .annotations import TEXT_TAG


def paint_annotations(painter, project, width, height, annotations, format_length):
    import numpy as np
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPen

    points = np.asarray([point for item in annotations for point in item.points], dtype=float)
    projected = iter(project(points, width, height))
    painter.save()
    try:
        painter.setClipRect(QRectF(0, 0, width, height))
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        font = painter.font()
        for item in annotations:
            screen = tuple(next(projected) for _ in item.points)
            if any(not all(map(math.isfinite, point)) or point[2] <= 0 for point in screen):
                continue
            color = QColor(*item.color.rgb)
            coordinates = [QPointF(x, y) for x, y, _ in screen]
            if item.kind == TEXT_TAG:
                anchor, = coordinates
                label = item.text
            else:
                start, end, a, b = coordinates
                anchor = (a+b)/2
                label = ' '.join(filter(None, (item.text, format_length(item.length))))
                painter.setPen(QPen(color, 1.25))
                painter.drawLine(start, a)
                painter.drawLine(end, b)
                painter.drawLine(a, b)
                dx, dy = b.x()-a.x(), b.y()-a.y()
                length = math.hypot(dx, dy)
                if length >= 2:
                    tick = QPointF((dx-dy)*4/length, (dy+dx)*4/length)
                    for end_point in (a, b):
                        painter.drawLine(end_point-tick, end_point+tick)
            if not label:
                continue
            font.setPixelSize(round(item.size))
            painter.setFont(font)
            metrics = painter.fontMetrics()
            label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, max(30, width-24))
            box_width, box_height = metrics.horizontalAdvance(label)+14, metrics.height()+8
            box = QRectF(anchor.x()-box_width/2, anchor.y()-box_height/2, box_width, box_height)
            painter.setPen(QPen(color, 1.2))
            painter.setBrush(QColor(27, 32, 36, 240))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QColor(245, 246, 248))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
    finally:
        painter.restore()


def install_annotation_renderer(viewport_class):
    native = viewport_class._paint_dots
    if getattr(native, '_noodles_annotations', False):
        return

    def draw(viewport, width, height):
        result = native(viewport, width, height)
        adapter = getattr(viewport.window(), '_noodles_preview_adapter', None)
        if adapter and viewport.space == 'model' and viewport.display_mode != 'technical':
            adapter.draw_annotations(viewport, width, height)
        return result

    draw._noodles_annotations = True
    viewport_class._paint_dots = draw


def paint_viewport_annotations(adapter, viewport, width, height):
    items = [item['annotation'] for item in adapter.visible(viewport.scene) if 'annotation' in item]
    if not items:
        return
    from OpenGL import GL
    from PySide6.QtGui import QPainter

    GL.glBindVertexArray(0)
    viewport._use(0)
    GL.glDisable(GL.GL_DEPTH_TEST)
    painter = QPainter(viewport)
    try:
        paint_annotations(painter, viewport.camera.project, width, height, items, viewport.scene.format_length)
        adapter.annotation_error = ''
    except Exception as exc:
        adapter.annotation_error = str(exc)
    finally:
        painter.end()
        GL.glEnable(GL.GL_DEPTH_TEST)
        viewport._reset_gl_state()
