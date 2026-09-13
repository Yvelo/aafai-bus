# -*- coding: utf-8 -*-
"""Unit tests for the DocSend page image helpers."""

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.actions import docsend_scraping


def test_is_blank_image_detects_uniform_page():
    black_page = Image.new('RGB', (10, 10), (0, 0, 0))
    assert docsend_scraping._is_blank_image(black_page) is True


def test_is_blank_image_accepts_page_with_content():
    page = Image.new('RGB', (10, 10), (255, 255, 255))
    page.putpixel((5, 5), (0, 0, 0))
    assert docsend_scraping._is_blank_image(page) is False


def test_transparent_image_is_flattened_on_white():
    transparent = Image.new('RGBA', (4, 4), (0, 0, 0, 0))
    flattened = docsend_scraping._to_rgb_on_white(transparent)
    assert flattened.mode == 'RGB'
    assert flattened.getpixel((0, 0)) == (255, 255, 255)
