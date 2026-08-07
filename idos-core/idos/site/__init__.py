"""IDOS Static Site Generator.

Genera una UI estática (HTML + JSON) a partir de los artefactos del journal,
conocimiento y cache de precios, publicable en GitHub Pages sin un servidor.
"""

from idos.site import builder  # noqa: F401

__all__ = ["builder"]