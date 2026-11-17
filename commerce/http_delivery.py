"""Negotiate compression for static inline HTML, leaving API bodies unchanged."""
from functools import lru_cache
import gzip
import math


def accepts_gzip(value):
    weights = {}
    for item in (value or '').split(','):
        coding, *parameters = item.strip().lower().split(';')
        if not coding:
            continue
        quality = 1.0
        for parameter in parameters:
            name, separator, weight = parameter.strip().partition('=')
            if name.strip() == 'q':
                try:
                    quality = float(weight) if separator else 0.0
                except ValueError:
                    quality = 0.0
        weights[coding] = quality if math.isfinite(quality) and 0 <= quality <= 1 else 0.0
    return weights.get('gzip', weights.get('*', 0.0)) > 0


@lru_cache(maxsize=4)
def _gzip_html(content):
    return gzip.compress(content, compresslevel=6, mtime=0)


def encode_html(content, accept_encoding):
    if len(content) >= 1024 and accepts_gzip(accept_encoding):
        encoded = _gzip_html(content)
        if len(encoded) < len(content):
            return encoded, {'Content-Encoding': 'gzip', 'Vary': 'Accept-Encoding'}
    return content, {'Vary': 'Accept-Encoding'}
