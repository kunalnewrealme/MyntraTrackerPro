import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class ProductStorage:
    DEFAULT_FIELDS = [
        'url',
        'product',
        'brand',
        'price',
        'target_price',
        'original_price',
        'discount',
        'stock',
        'favorite',
        'last_checked',
        'lowest_price',
        'highest_price',
    ]

    def __init__(self, products_path: str = None) -> None:
        self.base_path = self._get_application_root()
        self.products_file = (
            Path(products_path)
            if products_path
            else self.base_path / 'data' / 'products.json'
        )
        self.history_file = self.base_path / 'data' / 'price_history.json'
        self.products_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_products_file()
        self._ensure_history_file()

    def _get_application_root(self) -> Path:
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _ensure_products_file(self) -> None:
        if not self.products_file.exists():
            self.products_file.write_text('[]', encoding='utf-8')

    def _ensure_history_file(self) -> None:
        if not self.history_file.exists():
            self.history_file.write_text('[]', encoding='utf-8')

    def _load_history(self) -> List[Dict[str, Any]]:
        try:
            raw_text = self.history_file.read_text(encoding='utf-8')
            data = json.loads(raw_text or '[]')
            if not isinstance(data, list):
                logging.warning('History file did not contain a list; resetting file.')
                return []
            return data
        except Exception:
            logging.exception('Unable to load price history')
            return []

    def _save_history(self, history: List[Dict[str, Any]]) -> None:
        try:
            self.history_file.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            logging.exception('Unable to save price history')

    def _create_history_record(self, product: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'url': product.get('url', ''),
            'product': product.get('product', ''),
            'price': product.get('price', ''),
            'stock': product.get('stock', ''),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def load_products(self) -> List[Dict[str, Any]]:
        try:
            raw_text = self.products_file.read_text(encoding='utf-8')
            data = json.loads(raw_text or '[]')
            if not isinstance(data, list):
                logging.warning('Products file did not contain a list; resetting file.')
                data = []
        except Exception as exc:
            logging.exception('Unable to load products.json')
            data = []

        products = [self._normalize_product(item) for item in data]
        self._update_price_ranges(products)
        return products

    def save_products(self, products: List[Dict[str, Any]]) -> None:
        try:
            normalized = [self._normalize_product(item) for item in products]
            previous_products = self.load_products()
            self._append_history_for_refreshes(previous_products, normalized)
            self._update_price_ranges(normalized)
            self.products_file.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding='utf-8')
            logging.info('Saved %d products to %s', len(normalized), self.products_file)
        except Exception:
            logging.exception('Unable to save products.json')

    def _append_history_for_refreshes(
        self,
        old_products: List[Dict[str, Any]],
        new_products: List[Dict[str, Any]],
    ) -> None:
        old_map = {item.get('url', ''): item for item in old_products if item.get('url')}
        history = self._load_history()
        appended = False
        for product in new_products:
            url = product.get('url', '')
            if not url:
                continue
            old_product = old_map.get(url)
            if not product.get('last_checked'):
                continue
            if old_product is None or product.get('last_checked') != old_product.get('last_checked'):
                history.append(self._create_history_record(product))
                appended = True
        if appended:
            self._save_history(history)

    def _update_price_ranges(self, products: List[Dict[str, Any]]) -> None:
        history = self._load_history()
        prices_by_url: Dict[str, list[float]] = {}
        for record in history:
            url = record.get('url', '')
            price_value = self._parse_price_number(record.get('price', ''))
            if url and price_value is not None:
                prices_by_url.setdefault(url, []).append(price_value)

        for product in products:
            url = product.get('url', '')
            current_price = self._parse_price_number(product.get('price', ''))
            price_list = list(prices_by_url.get(url, []))
            if current_price is not None:
                price_list.append(current_price)
            if not price_list:
                product['lowest_price'] = ''
                product['highest_price'] = ''
                continue
            lowest = min(price_list)
            highest = max(price_list)
            product['lowest_price'] = f'₹{int(lowest)}' if lowest.is_integer() else f'₹{lowest:.2f}'
            product['highest_price'] = f'₹{int(highest)}' if highest.is_integer() else f'₹{highest:.2f}'

    def _parse_price_number(self, price: str) -> float | None:
        if not price:
            return None
        numeric = ''.join(ch for ch in price if ch.isdigit() or ch == '.')
        try:
            return float(numeric)
        except ValueError:
            return None

    def create_empty_product(self, url: str) -> Dict[str, Any]:
        product = {field: '' for field in self.DEFAULT_FIELDS}
        product['url'] = url
        product['target_price'] = '0'
        product['favorite'] = False
        return product

    def _normalize_product(self, product: Any) -> Dict[str, Any]:
        normalized = {field: '' for field in self.DEFAULT_FIELDS}
        if isinstance(product, dict):
            for field in self.DEFAULT_FIELDS:
                if field == 'target_price':
                    normalized[field] = str(product.get(field, 0) or 0)
                elif field == 'favorite':
                    normalized[field] = bool(product.get(field, False))
                else:
                    normalized[field] = str(product.get(field, '') or '')
        return normalized
