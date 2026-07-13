import logging
import time
from PySide6.QtCore import QThread, Signal

from tracker import MyntraTracker


class RefreshWorker(QThread):
    product_updated = Signal(dict)
    change_signal = Signal(tuple)
    target_price_reached = Signal(dict)
    error = Signal(str)
    progress_changed = Signal(dict)
    refresh_summary = Signal(dict)

    def __init__(self, products: list[dict]) -> None:
        super().__init__()
        self.products = products

    def run(self) -> None:
        start_time = time.time()
        # Initialize counters
        checked = 0
        success = 0
        failed = 0
        price_drop = 0
        price_up = 0
        stock_changed = 0
        back_in_stock = 0
        out_of_stock = 0
        target_hit = 0

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
                # Emit summary for zero performed
                duration = time.time() - start_time
                try:
                    self.refresh_summary.emit({
                        'checked': checked,
                        'success': success,
                        'failed': len([p for p in self.products if p.get('url')]),
                        'price_drop': price_drop,
                        'price_up': price_up,
                        'stock_changed': stock_changed,
                        'back_in_stock': back_in_stock,
                        'out_of_stock': out_of_stock,
                        'target_hit': target_hit,
                        'duration_seconds': duration,
                    })
                except Exception:
                    pass
                return

            total = len(self.products)
            for idx, product in enumerate(self.products, start=1):
                if self.isInterruptionRequested():
                    break
                url = product.get('url', '')
                # Emit progress BEFORE starting the fetch so UI shows current product immediately
                product_name = product.get('product') or url
                try:
                    percent = int((idx / total) * 100) if total > 0 else 0
                except Exception:
                    percent = 0
                try:
                    self.progress_changed.emit({
                        "current": idx,
                        "total": total,
                        "percent": percent,
                        "product": product_name,
                    })
                except Exception:
                    # Ensure worker continues even if UI slot fails
                    pass

                if not url:
                    # skip products without URL but still count toward total via percent
                    continue

                # Mark that we attempted this product
                checked += 1
                had_success = False
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

                        # Price change detection and counting
                        if old_price != new_price and old_price and new_price:
                            try:
                                old_val = float(''.join(ch for ch in str(old_price) if ch.isdigit() or ch == '.'))
                                new_val = float(''.join(ch for ch in str(new_price) if ch.isdigit() or ch == '.'))
                                if new_val < old_val:
                                    price_drop += 1
                                elif new_val > old_val:
                                    price_up += 1
                            except Exception:
                                pass
                            self.change_signal.emit(('price_changed', old_price, new_price, product_name))

                        # Stock change detection and counting
                        if old_stock != new_stock and old_stock and new_stock:
                            try:
                                old_s = str(old_stock).strip().lower()
                                new_s = str(new_stock).strip().lower()
                                stock_changed += 1
                                if old_s == 'out of stock' and new_s == 'in stock':
                                    back_in_stock += 1
                                if old_s == 'in stock' and new_s == 'out of stock':
                                    out_of_stock += 1
                            except Exception:
                                pass
                            self.change_signal.emit(('stock_changed', old_stock, new_stock, product_name))

                        # Target price reached
                        if self._is_price_reached(new_price, target_price) and not self._was_already_at_target(old_price, target_price):
                            target_hit += 1
                            self.target_price_reached.emit(updated)

                        # Successful update
                        self.product_updated.emit(updated)
                        had_success = True
                        success += 1
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
                # After attempting this product, if we did not succeed, count as failed (unless interrupted)
                if self.isInterruptionRequested():
                    break
                if not had_success:
                    failed += 1
        finally:
            try:
                if browser is not None or playwright is not None:
                    MyntraTracker.close_browser(playwright, browser)
            except Exception:
                pass

        # Emit final refresh summary
        try:
            duration = time.time() - start_time
            self.refresh_summary.emit({
                'checked': checked,
                'success': success,
                'failed': failed,
                'price_drop': price_drop,
                'price_up': price_up,
                'stock_changed': stock_changed,
                'back_in_stock': back_in_stock,
                'out_of_stock': out_of_stock,
                'target_hit': target_hit,
                'duration_seconds': duration,
            })
        except Exception:
            pass

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
