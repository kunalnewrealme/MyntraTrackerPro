import logging
from PySide6.QtCore import QThread, Signal

from tracker import MyntraTracker


class RefreshWorker(QThread):
    product_updated = Signal(dict)
    change_signal = Signal(tuple)
    target_price_reached = Signal(dict)
    finished = Signal()
    error = Signal(str)

    def __init__(self, products: list[dict]) -> None:
        super().__init__()
        self.products = products

    def run(self) -> None:
        for product in self.products:
            if self.isInterruptionRequested():
                break
            url = product.get('url', '')
            if not url:
                continue
            try:
                updated = MyntraTracker.fetch_product(url)
                if self.isInterruptionRequested():
                    break
                old_price = product.get('price', '')
                new_price = updated.get('price', '')
                old_stock = product.get('stock', '')
                new_stock = updated.get('stock', '')
                target_price = product.get('target_price', '0')
                product_name = updated.get('product') or product.get('product', '') or url
                if old_price != new_price and old_price and new_price:
                    self.change_signal.emit(('price_changed', old_price, new_price, product_name))
                if old_stock != new_stock and old_stock and new_stock:
                    self.change_signal.emit(('stock_changed', old_stock, new_stock, product_name))
                if self._is_price_reached(new_price, target_price) and not self._was_already_at_target(old_price, target_price):
                    self.target_price_reached.emit(updated)
                self.product_updated.emit(updated)
            except Exception as exc:
                logging.exception('Error refreshing product %s', url)
                self.error.emit(f'Unable to refresh {url}: {exc}')
        self.finished.emit()

    def _is_price_reached(self, current_price: str, target_price: str) -> bool:
        try:
            current_value = float(''.join(ch for ch in str(current_price) if ch.isdigit() or ch == '.'))
            target_value = float(''.join(ch for ch in str(target_price) if ch.isdigit() or ch == '.'))
        except ValueError:
            return False
        return target_value > 0 and current_value <= target_value

    def _was_already_at_target(self, old_price: str, target_price: str) -> bool:
        if not old_price:
            return False
        try:
            old_value = float(''.join(ch for ch in str(old_price) if ch.isdigit() or ch == '.'))
            target_value = float(''.join(ch for ch in str(target_price) if ch.isdigit() or ch == '.'))
        except ValueError:
            return False
        return target_value > 0 and old_value <= target_value


class AutoRefreshThread(QThread):
    refresh_triggered = Signal()

    def run(self) -> None:
        while not self.isInterruptionRequested():
            for _ in range(300):
                if self.isInterruptionRequested():
                    return
                self.msleep(1000)
            self.refresh_triggered.emit()
