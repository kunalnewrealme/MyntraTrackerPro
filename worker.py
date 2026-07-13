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
        playwright = None
        browser = None
        try:
            try:
                playwright, browser = MyntraTracker.open_browser(headless=False)
            except Exception as exc:
                logging.exception('Unable to start browser for refresh worker')
                for product in self.products:
                    url = product.get('url', '')
                    if url:
                        self.error.emit(f'Unable to refresh {url}: {exc}')
                return

            for product in self.products:
                if self.isInterruptionRequested():
                    break
                url = product.get('url', '')
                if not url:
                    continue

                retry_current_product = True
                while True:
                    if self.isInterruptionRequested():
                        break
                    try:
                        updated = MyntraTracker.fetch_product(url, browser=browser)
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
                        break
                    except Exception as exc:
                        if retry_current_product and not self._is_browser_usable(browser):
                            retry_current_product = False
                            logging.warning('Browser became unusable during refresh for %s; restarting browser.', url)
                            try:
                                MyntraTracker.close_browser(playwright, browser)
                            except Exception:
                                pass
                            try:
                                playwright, browser = MyntraTracker.open_browser(headless=True)
                                continue
                            except Exception as browser_exc:
                                logging.exception('Unable to restart browser for %s', url)
                                self.error.emit(f'Unable to refresh {url}: {browser_exc}')
                                break
                        logging.exception('Error refreshing product %s', url)
                        self.error.emit(f'Unable to refresh {url}: {exc}')
                        break
        finally:
            try:
                if browser is not None or playwright is not None:
                    MyntraTracker.close_browser(playwright, browser)
            except Exception:
                pass
            self.finished.emit()

    def _is_browser_usable(self, browser) -> bool:
        if browser is None:
            return False
        try:
            return browser.is_connected()
        except Exception:
            return False

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
