import logging
import platform

from plyer import notification


import time

class Notifier:
    _last_sent: dict[tuple[str, str], float] = {}

    @staticmethod
    def notify(title: str, message: str) -> None:
        try:
            key = (title, message)
            now = time.time()
            last_sent = Notifier._last_sent.get(key)
            if last_sent and now - last_sent < 30:
                return
            notification.notify(
                title='Myntra Tracker Pro',
                message=message,
                app_name='Myntra Tracker Pro',
                timeout=8,
            )
            Notifier._last_sent[key] = now
            logging.info('Notification shown: %s - %s', title, message)
        except Exception:
            logging.exception('Unable to send notification')

    @staticmethod
    def notify_price_change(product: str, old_price: str, new_price: str) -> None:
        title = 'Price Decreased'
        message = f'{product}\nPrice dropped from ₹{old_price} to ₹{new_price}'
        Notifier.notify(title, message)

    @staticmethod
    def notify_stock_change(product: str) -> None:
        title = 'In Stock'
        message = f'{product}\nProduct is back in stock'
        Notifier.notify(title, message)

    @staticmethod
    def notify_target_price_reached(product: str, price: str, target: str) -> None:
        title = 'Target Price Reached'
        message = f'{product}\nTarget price reached\nCurrent Price: ₹{price}\nTarget Price: ₹{target}'
        Notifier.notify(title, message)
        try:
            if platform.system() == 'Windows':
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            logging.exception('Unable to play notification sound')
