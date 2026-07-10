import logging

from plyer import notification


class Notifier:
    @staticmethod
    def notify(title: str, message: str) -> None:
        try:
            notification.notify(
                title=title,
                message=message,
                app_name='Myntra Tracker Pro',
                timeout=8,
            )
            logging.info('Notification shown: %s - %s', title, message)
        except Exception:
            logging.exception('Unable to send notification')

    @staticmethod
    def notify_price_change(product: str, old_price: str, new_price: str) -> None:
        title = 'Price Updated'
        message = f'{product}\n₹{old_price} → ₹{new_price}'
        Notifier.notify(title, message)

    @staticmethod
    def notify_stock_change(product: str, stock: str) -> None:
        title = 'Stock Changed'
        message = f'{product}\nNow:\n{stock}'
        Notifier.notify(title, message)

    @staticmethod
    def notify_target_price_reached(product: str, price: str, target: str) -> None:
        title = 'Target Price Reached'
        message = f'{product}\nCurrent Price:\n₹{price}\n\nTarget:\n₹{target}'
        Notifier.notify(title, message)
