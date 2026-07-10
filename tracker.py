import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from playwright.sync_api import Error, TimeoutError, sync_playwright


class MyntraTracker:
    USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/138.0.0.0 Safari/537.36'
    )
    VIEWPORT = {'width': 1366, 'height': 768}
    MAX_RETRIES = 3

    @staticmethod
    def _get_application_root() -> Path:
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, (int, float)):
            return str(value)
        return str(value).strip()

    @staticmethod
    def _parse_price_text(text: str) -> str:
        if not text:
            return ''
        normalized = text.replace('â‚¹', '₹').replace('\xa0', ' ').strip()
        match = re.search(r'₹\s*[\d,]+(?:\.\d+)?', normalized)
        if match:
            return match.group(0).replace(' ', '')
        fallback = re.search(r'[\d,]+(?:\.\d+)?', normalized)
        if fallback:
            return '₹' + fallback.group(0).replace(',', '')
        return normalized

    @staticmethod
    def _to_number(price: str) -> Optional[float]:
        if not price:
            return None
        cleaned = re.sub(r'[^\d.]', '', price)
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def _install_chromium(cls) -> None:
        logging.info('Installing Playwright Chromium browser binaries...')
        subprocess.run(
            [sys.executable, '-m', 'playwright', 'install', 'chromium'],
            check=True,
        )

    @classmethod
    def _read_json_ld(cls, page) -> Dict[str, Any]:
        scripts = page.locator('script[type="application/ld+json"]').all_text_contents()
        for script in scripts:
            if not script:
                continue
            try:
                obj = json.loads(script)
            except Exception:
                continue
            if isinstance(obj, dict):
                if obj.get('@type') == 'Product':
                    return obj
                if '@graph' in obj and isinstance(obj['@graph'], list):
                    for item in obj['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Product':
                            return item
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and item.get('@type') == 'Product':
                        return item
        return {}

    @classmethod
    def _extract_brand_from_og_title(cls, page) -> str:
        try:
            content = page.locator('meta[property="og:title"]').first.get_attribute('content') or ''
            content = content.replace('Buy ', '').strip()
            if not content:
                return ''
            for separator in [' - ', ' | ', ': ', ' by ']:
                if separator in content:
                    candidate = content.split(separator)[0].strip()
                    if candidate:
                        return cls._shorten_brand_candidate(candidate)
            return cls._shorten_brand_candidate(content)
        except Exception:
            return ''

    @classmethod
    def _extract_brand_from_title_text(cls, text: str) -> str:
        if not text:
            return ''
        text = text.replace('Buy ', '').replace(' | Myntra', '').strip()
        for separator in [' - ', ' | ', ': ', ' by ']:
            if separator in text:
                candidate = text.split(separator)[0].strip()
                if candidate:
                    return cls._shorten_brand_candidate(candidate)
        return cls._shorten_brand_candidate(text)

    @classmethod
    def _shorten_brand_candidate(cls, candidate: str) -> str:
        candidate = candidate.strip()
        if not candidate:
            return ''
        words = candidate.split()
        if len(words) == 1:
            return candidate
        if words[1] == '&' and len(words) >= 3:
            return ' '.join(words[:3])
        if any(char.isdigit() for char in words[1]):
            return words[0]
        if words[1].lower() in {
            'set', 'pack', 'for', 'with', 'and', 'of', 'single', 'pair',
            'women', 'men', 'black', 'white', 'blue', 'red', 'green',
            'matte', 'finish', 'product', 'kajal', 'eyeconic', 'eyeliner',
        }:
            return words[0]
        if words[0][0].isupper() and words[1][0].isupper():
            if len(words) >= 3 and words[2][0].isupper():
                return ' '.join(words[:3])
            return f'{words[0]} {words[1]}'
        return words[0]

    @classmethod
    def _extract_from_json_ld(cls, page) -> Dict[str, str]:
        raw = cls._read_json_ld(page)
        if not raw:
            return {}

        brand = raw.get('brand')
        if isinstance(brand, dict):
            brand = brand.get('name') or brand.get('@id')
        elif isinstance(brand, list) and brand:
            first_brand = brand[0]
            if isinstance(first_brand, dict):
                brand = first_brand.get('name') or first_brand.get('@id')
            else:
                brand = first_brand

        image = raw.get('image')
        if isinstance(image, list):
            image = image[0] if image else ''
        if isinstance(image, dict):
            image = image.get('url') or image.get('src') or ''

        offers = raw.get('offers')
        if isinstance(offers, list) and offers:
            offers = offers[0]

        price = ''
        original_price = ''
        discount = ''
        stock = ''
        product_name = ''

        if isinstance(offers, dict):
            price = cls._normalize_text(
                offers.get('price')
                or offers.get('lowPrice')
                or offers.get('priceSpecification', {}).get('price', '')
            )
            original_price = cls._normalize_text(
                offers.get('highPrice')
                or offers.get('listPrice')
                or offers.get('priceSpecification', {}).get('price', '')
            )
            discount = cls._normalize_text(
                offers.get('discount') or offers.get('discountPercentage')
            )
            availability = cls._normalize_text(offers.get('availability')).lower()
            if 'instock' in availability:
                stock = 'In Stock'
            elif 'outofstock' in availability:
                stock = 'Out of Stock'

        if not discount and price and original_price:
            current_value = cls._to_number(price)
            original_value = cls._to_number(original_price)
            if current_value is not None and original_value is not None and original_value > current_value:
                discount = f'{int(round((original_value - current_value) / original_value * 100))}% OFF'

        try:
            product_name = cls._normalize_text(raw.get('name'))
        except Exception:
            product_name = ''

        if not product_name:
            try:
                page_title = page.title() or ''
                product_name = page_title.replace('Buy ', '').replace(' | Myntra', '').strip()
            except Exception:
                product_name = ''

        return {
            'product': product_name,
            'brand': cls._normalize_text(brand),
            'image': cls._normalize_text(image),
            'price': cls._parse_price_text(price),
            'original_price': cls._parse_price_text(original_price),
            'discount': discount,
            'stock': stock,
        }

    @classmethod
    def _extract_using_page(cls, page) -> Dict[str, str]:
        result = {
            'product': '',
            'brand': '',
            'image': '',
            'price': '',
            'original_price': '',
            'discount': '',
            'stock': '',
        }
        try:
            page_title = page.title() or ''
            result['product'] = page_title.replace('Buy ', '').replace(' | Myntra', '').strip()
            if not result['brand']:
                result['brand'] = cls._extract_brand_from_title_text(page_title)
        except Exception:
            pass

        try:
            body = page.locator('body').first.inner_text() or ''
        except Exception:
            body = ''

        body = body.replace('â‚¹', '₹').replace('\xa0', ' ')

        if body:
            lowered_body = body.lower()
            if 'out of stock' in lowered_body or 'sold out' in lowered_body:
                result['stock'] = 'Out of Stock'
            else:
                result['stock'] = 'In Stock'

            prices = re.findall(r'₹\s*[\d,]+(?:\.\d+)?', body)
            if prices:
                result['price'] = cls._parse_price_text(prices[0])
                if len(prices) > 1:
                    result['original_price'] = cls._parse_price_text(prices[1])

            if not result['brand']:
                brand_match = re.search(r'Brand\s*[:\-]\s*([^\n\r]+)', body, re.IGNORECASE)
                if brand_match:
                    result['brand'] = brand_match.group(1).strip().rstrip('.')

        if result['price'] and result['original_price']:
            current_value = cls._to_number(result['price'])
            original_value = cls._to_number(result['original_price'])
            if current_value is not None and original_value is not None and original_value > current_value:
                result['discount'] = f'{int(round((original_value - current_value) / original_value * 100))}% OFF'
 
        if not result['image']:
            try:
                image_url = page.locator('meta[property="og:image"]').first.get_attribute('content') or ''
                result['image'] = cls._normalize_text(image_url)
            except Exception:
                pass
 
        return result

    @classmethod
    def _launch_browser(cls, headless: bool):
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(
                headless=headless,
                args=['--disable-blink-features=AutomationControlled'],
            )
            return playwright, browser
        except Error as error:
            message = str(error).lower()
            if 'browser is not installed' in message or 'could not find browser' in message or 'executable not found' in message:
                cls._install_chromium()
                browser = playwright.chromium.launch(
                    headless=headless,
                    args=['--disable-blink-features=AutomationControlled'],
                )
                return playwright, browser
            playwright.stop()
            raise

    @classmethod
    def _navigate_page(cls, page, url: str) -> None:
        logging.info('Navigating to %s', url)
        page.goto(url, wait_until='load', timeout=90000)
        logging.info('Navigation completed for %s', url)
        page.wait_for_timeout(1500)

    @classmethod
    def fetch_product(cls, url: str) -> Dict[str, str]:
        logging.info('Fetching product data for %s', url)
        last_exception: Optional[Exception] = None

        for attempt in range(1, cls.MAX_RETRIES + 1):
            playwright = None
            browser = None
            page = None
            try:
                headless = False if attempt == 1 else True
                logging.info('Starting browser for attempt %d (headless=%s)', attempt, headless)
                playwright, browser = cls._launch_browser(headless)
                page = browser.new_page()
                try:
                    page.set_viewport_size(cls.VIEWPORT)
                except Exception:
                    pass
                try:
                    page.set_extra_http_headers({'User-Agent': cls.USER_AGENT})
                except Exception:
                    pass
                try:
                    cls._navigate_page(page, url)
                except Exception as navigation_error:
                    last_exception = navigation_error
                    logging.exception('Navigation failed on attempt %d for %s', attempt, url)
                    raise navigation_error
                result = {
                    'url': url,
                    'product': '',
                    'brand': '',
                    'image': '',
                    'price': '',
                    'original_price': '',
                    'discount': '',
                    'stock': '',
                    'last_checked': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                }
                try:
                    json_data = cls._extract_from_json_ld(page)
                    for key, value in json_data.items():
                        if value:
                            result[key] = value
                except Exception:
                    logging.exception('JSON-LD extraction failed for %s', url)
                try:
                    page_data = cls._extract_using_page(page)
                    for key, value in page_data.items():
                        if value and not result.get(key):
                            result[key] = value
                except Exception:
                    logging.exception('Fallback extraction failed for %s', url)
                if not result['brand']:
                    try:
                        result['brand'] = cls._extract_brand_from_og_title(page)
                    except Exception:
                        pass
                if not result['stock']:
                    try:
                        body_text = page.locator('body').first.inner_text() or ''
                        if 'out of stock' in body_text.lower() or 'sold out' in body_text.lower():
                            result['stock'] = 'Out of Stock'
                        else:
                            result['stock'] = 'In Stock'
                    except Exception:
                        result['stock'] = 'In Stock'
                if not result['product']:
                    try:
                        result['product'] = page.title().replace('Buy ', '').replace(' | Myntra', '').strip()
                    except Exception:
                        result['product'] = ''
                return result
            except Exception as exc:
                last_exception = exc
                logging.exception('Attempt %d failed for %s', attempt, url)
                if attempt < cls.MAX_RETRIES:
                    logging.info('Restarting browser and retrying %s after attempt %d', url, attempt)
                    time.sleep(2)
                    continue
                raise
            finally:
                try:
                    if page is not None:
                        page.close()
                except Exception:
                    pass
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
                try:
                    if playwright is not None:
                        playwright.stop()
                except Exception:
                    pass
        if last_exception:
            raise last_exception
