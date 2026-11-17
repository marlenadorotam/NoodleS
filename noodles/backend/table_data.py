"""Bounded local CSV reads and scalar choices for data nodes."""
import csv
import io
import json
from pathlib import Path
import re

from .arithmetic import finite_number
from .datatree import Branch, DataTree, MAX_BRANCHES, MAX_ITEMS, aligned


CSV_DELIMITERS = (',', ';', '\t')
MAX_CSV_BYTES = 4 * 1024 * 1024
DEFAULT_CHOICES = 'Option A = 0\nOption B = 1'


def choice_entries(text):
    if not isinstance(text, str) or len(text) > 16384:
        raise ValueError('Value List options must be text up to 16,384 characters.')
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        label, separator, value = line.partition('=')
        label, value = label.strip(), value.strip()
        if not label or not separator or not value:
            raise ValueError('Use one Label = Value pair per line.')
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            parsed = value
        if type(parsed) in (int, float):
            finite_number(parsed)
        elif type(parsed) not in (str, bool):
            raise ValueError('Value List values must be numbers, true/false or text.')
        entries.append((label, parsed))
    if not entries or len(entries) > 256 or len({label for label, _ in entries}) != len(entries):
        raise ValueError('Value List needs 1–256 options with distinct labels.')
    return tuple(entries)


def _number_cell(value, delimiter):
    token = value.strip()
    if delimiter != ',':
        token = token.replace(',', '.')
    if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', token):
        return finite_number(float(token))
    return value


def _read_rows(filename, delimiter, header, parse_numbers, budget, graph_directory):
    if not filename:
        raise ValueError('Choose a CSV file in Properties or connect its path.')
    path = Path(filename)
    if filename.startswith(('\\\\', '//')) or (path.anchor and not path.is_absolute()):
        raise ValueError('Read CSV requires a local file path.')
    if not path.is_absolute():
        if graph_directory is None:
            raise ValueError('Save or open a graph to use a relative CSV path.')
        path = graph_directory / path
        if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
            raise ValueError('Read CSV requires a local file path.')
    try:
        if not path.is_file():
            raise ValueError('CSV path does not point to a file.')
        with path.open('rb') as stream:
            content = stream.read(budget[0] + 1)
        if len(content) > budget[0]:
            raise ValueError('Read CSV can read up to 4 MiB per evaluation.')
        budget[0] -= len(content)
        encoding = 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        rows = csv.reader(io.StringIO(content.decode(encoding), newline=''), delimiter=delimiter, strict=True)
        headings = tuple(next(rows, ())) if header else ()
        data, count = [], len(headings)
        for row in rows:
            if not row:
                continue
            count += len(row)
            if count > MAX_ITEMS:
                raise ValueError('Read CSV exceeds the 10,000-cell limit.')
            data.append(tuple(_number_cell(cell, delimiter) for cell in row) if parse_numbers else tuple(row))
        if count > MAX_ITEMS:
            raise ValueError('Read CSV exceeds the 10,000-cell limit.')
        return headings, tuple(data)
    except UnicodeError as exc:
        raise ValueError('CSV text must use UTF-8 or UTF-16 with a byte-order mark.') from exc
    except (OSError, csv.Error) as exc:
        raise ValueError(f'Could not read CSV: {exc}') from exc


def read_csv(trees, graph_directory=None):
    matches = tuple(aligned(*(trees[port] for port in ('P', 'D', 'H', 'N'))))
    split = any(len(rows) > 1 for _, rows in matches)
    data, headers, counts = [], [], []
    cache, budget = {}, [MAX_CSV_BYTES]
    cells = 0
    for path, rows in matches:
        for index, (settings, _) in enumerate(rows):
            filename, separator, header, parse_numbers = settings
            if settings not in cache:
                cache[settings] = _read_rows(filename, CSV_DELIMITERS[separator], header, parse_numbers,
                                             budget, graph_directory)
            headings, table = cache[settings]
            cells += len(headings) + sum(map(len, table))
            if cells > MAX_ITEMS or len(data) + len(table) > MAX_BRANCHES:
                raise ValueError('Read CSV exceeds the 10,000-cell or row limit.')
            prefix = path + (index,) if split else path
            data.extend(Branch(prefix + (row,), values) for row, values in enumerate(table))
            headers.append(Branch(prefix, headings))
            counts.append(Branch(prefix, (len(table),)))
    return {'R': DataTree(tuple(data)), 'H': DataTree(tuple(headers)), 'N': DataTree(tuple(counts))}
