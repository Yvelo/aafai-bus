# -*- coding: utf-8 -*-
"""Unit tests for the Papermark scraping helpers."""

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.actions import papermark_scraping


class FakeDriver:
    """Minimal driver stub returning canned values for the executed scripts."""

    def __init__(self, body_text='', image_count=0):
        self.body_text = body_text
        self.image_count = image_count

    def execute_script(self, script, *args):
        if 'innerText' in script:
            return self.body_text
        if 'querySelectorAll' in script and 'length' in script:
            return self.image_count
        return None


def test_shared_image_helpers_are_reused_from_docsend():
    black_page = Image.new('RGB', (10, 10), (0, 0, 0))
    assert papermark_scraping._is_blank_image(black_page) is True

    transparent = Image.new('RGBA', (4, 4), (0, 0, 0, 0))
    flattened = papermark_scraping._to_rgb_on_white(transparent)
    assert flattened.mode == 'RGB'
    assert flattened.getpixel((0, 0)) == (255, 255, 255)


def test_indicator_total_is_read_from_the_toolbar():
    driver = FakeDriver(body_text='Papermark\n3\n/\n13')
    assert papermark_scraping._get_indicator_total(driver) == 13


def test_current_page_number_is_read_from_the_toolbar():
    driver = FakeDriver(body_text='Papermark\n3\n/\n13')
    assert papermark_scraping._get_current_page_number(driver) == 3


def test_current_page_number_is_zero_when_unknown():
    driver = FakeDriver(body_text='Papermark')
    assert papermark_scraping._get_current_page_number(driver) == 0


def test_total_pages_count_uses_the_highest_available_source():
    driver = FakeDriver(body_text='1 / 13', image_count=10)
    assert papermark_scraping._get_total_pages_count(driver) == 13

    driver = FakeDriver(body_text='', image_count=7)
    assert papermark_scraping._get_total_pages_count(driver) == 7

    driver = FakeDriver(body_text='', image_count=0)
    assert papermark_scraping._get_total_pages_count(driver) == 1


def test_execute_fails_fast_without_mandatory_parameters(tmp_path):
    results = {}

    def write_result(job_id, result):
        results[job_id] = result

    papermark_scraping.execute('job-1', {"url": None, "user_email": None}, str(tmp_path), write_result)

    assert results['job-1']['status'] == 'failed'
    assert 'Missing required parameters' in results['job-1']['error']
