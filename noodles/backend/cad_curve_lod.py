"""Convert physical screen accuracy to reusable OCC deflection levels."""
from dataclasses import dataclass
import math

PIXEL_ERROR = .5
LEVEL_RATIO = math.sqrt(2.)


@dataclass(frozen=True)
class CurveView:
    """Snapshot of a model pane, in physical pixels."""
    size: tuple
    eye: tuple
    basis: tuple
    focal: float
    near: float
    far: float
    distance: float
    parallel: bool

    @classmethod
    def from_pane(cls, pane):
        camera = getattr(pane, 'camera', None)
        if (camera is None or not pane.isVisible() or getattr(pane, 'space', 'model') != 'model'
                or pane.display_mode == 'technical' or min(pane.width(), pane.height()) < 2):
            return None
        dpr = pane.devicePixelRatioF()
        size = (pane.width() * dpr, pane.height() * dpr)
        focal = size[1] / (2 * math.tan(math.radians(camera.fov) / 2))
        near, far = camera.clip_planes()
        return cls(size, tuple(camera.position),
                   tuple(map(tuple, camera.view_matrix()[:3, :3])),
                   focal, near, far, camera.distance, camera.projection == 'parallel')

    def visible_scales(self, centers, radii):
        """Upper screen magnification on the visible part of each box.

        In perspective this bounds the derivative of the pinhole projection.
        Clip to the visible frustum before bounding depth and field angle so
        geometry crossing the eye plane does not request infinite precision.
        """
        import numpy as np

        basis = np.asarray(self.basis)
        x, y, depth = ((centers - self.eye) @ basis.T).T
        depth = -depth
        rx, ry, rz = (radii @ np.abs(basis).T).T
        # A pixel of leeway keeps curves crossing the edge in the queue.
        half_x, half_y = np.asarray(self.size) * .5 + 1.
        if self.parallel:
            scale = self.focal / self.distance
            visible = (np.abs(x) - rx <= half_x / scale) & (np.abs(y) - ry <= half_y / scale)
            return np.where(visible, scale, 0.)
        tan_x, tan_y = half_x / self.focal, half_y / self.focal
        nearest = np.maximum.reduce((depth - rz, np.full(len(depth), self.near),
                                     (np.abs(x) - rx) / tan_x, (np.abs(y) - ry) / tan_y))
        visible = nearest <= np.minimum(depth + rz, self.far)
        slope_x = np.minimum((np.abs(x) + rx) / nearest, tan_x)
        slope_y = np.minimum((np.abs(y) + ry) / nearest, tan_y)
        return np.where(visible, self.focal * np.sqrt(1 + slope_x**2 + slope_y**2) / nearest, 0.)


def level_for(scale, previous=None):
    """Refine at the threshold and leave extra room before coarsening."""
    if previous is not None and LEVEL_RATIO ** (previous - 1.5) < scale <= LEVEL_RATIO ** previous:
        return previous
    return math.ceil(math.log(scale, LEVEL_RATIO))


def deflection_for(level):
    return None if level is None else PIXEL_ERROR / LEVEL_RATIO ** level
