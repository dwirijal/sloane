import sys
import os

# Add scraper directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scraper'))

from engine import fetch_html
import asyncio

def test_fetch_html_success():
    # This is a basic structure test; actual network calls would require mocking
    assert callable(fetch_html)

def test_fetch_html_timeout():
    # Verify function signature accepts retries
    import inspect
    sig = inspect.signature(fetch_html)
    assert 'retries' in sig.parameters
    assert sig.parameters['retries'].default == 3