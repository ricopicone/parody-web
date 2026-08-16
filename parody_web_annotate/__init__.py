"""Freehand annotation of parody-web's per-section print PDFs.

A separate app from parody_web on purpose: core stays JavaScript-free and
knows nothing about users, while this app owns the reader's ink, the viewer
bundle, and the endpoints. Enable it by adding it to INSTALLED_APPS.
"""
