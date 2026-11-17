"""Transfer curves ported from Ryven; one mathematical source for plot and runtime."""
import math
from .arithmetic import finite_number


KIND_PARAMS = {
    'Linear': ('linear_a', 'linear_b'),
    'Bezier': ('bezier_x1', 'bezier_y1', 'bezier_x2', 'bezier_y2'),
    'Quadratic Bezier': ('quadratic_x', 'quadratic_y'),
    'Power': ('power_exponent',),
    'Parabola': ('parabola_peak_x', 'parabola_peak_y'),
    'Smoothstep': ('smoothstep_shape', 'smoothstep_start', 'smoothstep_end'),
    'Sigmoid': ('sigmoid_steepness',), 'Square Root': ('sqrt_exponent',),
    'Exponential': ('exponential_rate',), 'Sine': ('sine_frequency', 'sine_amplitude'),
    'Sine Summation': ('sine_sum_frequency', 'sine_sum_a1', 'sine_sum_a2'),
    'Gaussian': ('gaussian_center', 'gaussian_sigma'),
}
PARAM_LIMITS = {
    **{key: (0., 1.) for key in ('linear_a', 'linear_b', 'bezier_x1', 'bezier_y1',
        'bezier_x2', 'bezier_y2', 'quadratic_x', 'quadratic_y', 'gaussian_center')},
    'power_exponent': (.1, 10.), 'sqrt_exponent': (.1, 1.), 'smoothstep_shape': (.6, 4.),
    'parabola_peak_x': (.05, .95), 'parabola_peak_y': (.05, 1.),
    'smoothstep_start': (0., .95), 'smoothstep_end': (.05, 1.),
    'sigmoid_steepness': (.5, 24.), 'exponential_rate': (-12., 12.),
    'sine_frequency': (.25, 6.), 'sine_amplitude': (0., .5),
    'sine_sum_frequency': (.25, 6.), 'sine_sum_a1': (0., .5), 'sine_sum_a2': (-.5, .5),
    'gaussian_sigma': (.01, 1.),
}

KINDS = (
    'Linear', 'Bezier', 'Quadratic Bezier', 'Power', 'Parabola',
    'Smoothstep', 'Sigmoid', 'Square Root', 'Exponential',
    'Sine', 'Sine Summation', 'Gaussian',
)


def normalize_config(raw=None):
    """Validate historical graph settings, retaining legacy field names."""
    default = {
        'kind': 'Linear',
        'linear_a': 0.0, 'linear_b': 1.0,
        'bezier_x1': 0.25, 'bezier_y1': 0.25,
        'bezier_x2': 0.75, 'bezier_y2': 0.75,
        'quadratic_x': 0.5, 'quadratic_y': 0.5,
        'parabola_peak_x': 0.5, 'parabola_peak_y': 1.0,
        'smoothstep_start': 0.0, 'smoothstep_end': 1.0,
        'smoothstep_shape': 1.0,  # backward-compatible: 1 is classic smoothstep
        'sqrt_exponent': 0.5,
        'power_exponent': 2.5,
        'sigmoid_steepness': 10.0,
        'exponential_rate': 4.0,
        'sine_frequency': 1.0, 'sine_amplitude': 0.5,
        'sine_sum_frequency': 1.0,
        'sine_sum_a1': 0.30, 'sine_sum_a2': 0.12,
        'gaussian_center': 0.5, 'gaussian_sigma': 0.18,
        'reverse': False,    # legacy flag: flip output vertically (Flip Y)
        'flip_x': False,     # flip input horizontally (Flip X)
    }
    if raw is None:
        return default
    if not isinstance(raw, dict):
        raise ValueError('Graph Mapper settings must be an object')
    out = dict(default)
    kind = str(raw.get('kind', default['kind']))
    if kind not in KINDS:
        raise ValueError('Graph Mapper: unknown function ' + kind)
    out['kind'] = kind
    for key in default:
        if key in ('kind', 'reverse', 'flip_x'):
            continue
        out[key] = finite_number(raw.get(key, default[key]))
    for key in ('reverse', 'flip_x'):
        if type(raw.get(key, False)) is not bool:
            raise ValueError('Graph Mapper ' + key + ' must be Boolean')
        out[key] = bool(raw.get(key, False))
    for key in ('linear_a', 'linear_b', 'bezier_x1', 'bezier_y1',
                'bezier_x2', 'bezier_y2', 'quadratic_x', 'quadratic_y',
                'parabola_peak_x', 'parabola_peak_y',
                'smoothstep_start', 'smoothstep_end',
                'gaussian_center'):
        if not 0. <= out[key] <= 1.:
            raise ValueError('Graph Mapper ' + key + ' must lie in [0,1]')
    if out['bezier_x1'] > out['bezier_x2']:
        raise ValueError('Bezier handles must remain in increasing X order')
    if not 0.05 <= out['parabola_peak_x'] <= 0.95:
        raise ValueError('Parabola peak X must lie in [0.05, 0.95]')
    if not 0.05 <= out['parabola_peak_y'] <= 1.0:
        raise ValueError('Parabola peak Y must lie in [0.05, 1]')
    if out['smoothstep_end'] - out['smoothstep_start'] < 0.05 - 1.e-10:
        raise ValueError('Smoothstep handles must be separated by 0.05')
    limits = {
        'power_exponent': (0.1, 10.),
        'sqrt_exponent': (0.1, 1.0),
        'smoothstep_shape': (0.6, 4.0),
        'sigmoid_steepness': (0.5, 24.),
        'exponential_rate': (-12., 12.),
        'sine_frequency': (0.25, 6.),
        'sine_amplitude': (0., 0.5),
        'sine_sum_frequency': (0.25, 6.),
        'sine_sum_a1': (0., 0.5),
        'sine_sum_a2': (-0.5, 0.5),
        'gaussian_sigma': (0.01, 1.),
    }
    for key, (low, high) in limits.items():
        if not low <= out[key] <= high:
            raise ValueError('Graph Mapper ' + key + ' must lie in '
                             f'[{low},{high}]')
    return out


def logistic(z):
    """Stable logistic curve for steepness up to 24; no overflowing exp."""
    if z >= 0.:
        return 1. / (1. + math.exp(-z))
    e = math.exp(z)
    return e / (1. + e)


def exponential(x, rate):
    """Endpoint-normalized exponential; rate=0 is its linear limit."""
    if abs(rate) < 1e-10:
        return x
    if rate > 0.:
        return math.expm1(rate*x) / math.expm1(rate)
    # Stable for negative rates as well (both expm1 values are negative).
    return math.expm1(rate*x) / math.expm1(rate)


def unit_value(x, config):
    """0..1 transfer function shared by numeric node and Qt plot/editor."""
    x = min(1., max(0., finite_number(x)))
    if config.get('flip_x', False):
        x = 1. - x
    kind = config['kind']
    if kind == 'Linear':
        y = config['linear_a'] + (config['linear_b'] - config['linear_a']) * x
    elif kind == 'Bezier':
        if x in (0., 1.):
            return 1. - x if config.get('reverse', False) else x
        # Legacy cubic curve: exact inversion of the Bézier X(t) coordinate.
        x1, y1 = config['bezier_x1'], config['bezier_y1']
        x2, y2 = config['bezier_x2'], config['bezier_y2']
        left, right = 0., 1.
        for _ in range(36):
            t = .5 * (left + right)
            s = 1. - t
            x_t = 3*s*s*t*x1 + 3*s*t*t*x2 + t*t*t
            if x_t < x:
                left = t
            else:
                right = t
        t = .5*(left+right)
        s = 1. - t
        y = 3*s*s*t*y1 + 3*s*t*t*y2 + t*t*t
    elif kind == 'Quadratic Bezier':
        if x in (0., 1.):
            return 1. - x if config.get('reverse', False) else x
        # P0=(0,0), P1=(quadratic_x,quadratic_y), P2=(1,1).
        # Invert X(t), not just Y(t), so dragging X really affects the graph.
        cx, cy = config['quadratic_x'], config['quadratic_y']
        left, right = 0., 1.
        for _ in range(36):
            t = .5 * (left + right)
            s = 1. - t
            x_t = 2.*s*t*cx + t*t
            if x_t < x:
                left = t
            else:
                right = t
        t = .5*(left+right)
        y = 2.*(1.-t)*t*cy + t*t
    elif kind == 'Power':
        y = x ** config['power_exponent']
    elif kind == 'Parabola':
        # Two quadratic pieces joined with a shared horizontal tangent at
        # a draggable peak.  Default (.5, 1) is exactly 4*x*(1-x).
        peak_x = config['parabola_peak_x']
        local = (x - peak_x) / (peak_x if x <= peak_x else 1. - peak_x)
        y = config['parabola_peak_y'] * (1. - local*local)
    elif kind == 'Smoothstep':
        # The legacy Start/End interval still works for existing projects.
        # A vertical editor handle varies the ramp's bias while preserving
        # endpoint values and zero endpoint slopes (shape >= 0.6).
        start, end = config['smoothstep_start'], config['smoothstep_end']
        t = min(1., max(0., (x - start) / (end - start)))
        y = (t*t*(3.-2.*t)) ** config['smoothstep_shape']
    elif kind == 'Sigmoid':
        k = config['sigmoid_steepness']
        a = logistic(-.5*k)
        b = logistic(.5*k)
        y = (logistic(k*(x-.5))-a) / (b-a)
    elif kind == 'Square Root':
        # Generalized adjustable root family: exponent .5 is sqrt(x).
        y = x ** config['sqrt_exponent']
    elif kind == 'Exponential':
        y = exponential(x, config['exponential_rate'])
    elif kind == 'Sine':
        y = .5 - config['sine_amplitude'] * math.cos(
            2.*math.pi*config['sine_frequency']*x)
    elif kind == 'Sine Summation':
        f = config['sine_sum_frequency']
        y = (.5
             - config['sine_sum_a1']*math.cos(2.*math.pi*f*x)
             - config['sine_sum_a2']*math.cos(4.*math.pi*f*x))
    elif kind == 'Gaussian':
        z = (x-config['gaussian_center']) / config['gaussian_sigma']
        y = math.exp(-.5*z*z)
    else:
        raise ValueError('Unknown graph kind')
    y = min(1., max(0., y))
    return 1. - y if config.get('reverse', False) else y


def mapped_value(value, source, target, config):
    """Clamp to the signed source interval, map 0..1, then interpolate safely."""
    if source.start == source.end or target.start == target.end:
        raise ValueError('Graph Mapper domains must have nonzero length.')
    a, b = source.start, source.end
    if (a < b and value <= a) or (a > b and value >= a):
        x = 0.
    elif (a < b and value >= b) or (a > b and value <= b):
        x = 1.
    else:
        span = b - a
        if math.isfinite(span):
            x = (value - a) / span
        else:
            # Opposite large finite bounds can overflow their difference.
            scale = max(abs(a), abs(b))
            x = (value / scale - a / scale) / (b / scale - a / scale)
    y = unit_value(x, config)
    # Convex interpolation avoids overflowing d-c for valid finite endpoints.
    return finite_number((1. - y) * target.start + y * target.end)
