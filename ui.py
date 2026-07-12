import csv
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import winreg
except ImportError:
    winreg = None

import matplotlib
matplotlib.use('QtAgg')
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QMenu,
    QSystemTrayIcon,
    QStatusBar,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QCheckBox,
    QFormLayout,
    QInputDialog,
    QTextEdit,
)

from notifier import Notifier
from storage import ProductStorage
from worker import RefreshWorker


class MainWindow(QMainWindow):
    COLUMN_HEADERS = ['Image', 'Product', 'Favorite', 'Brand', 'Price', 'Target Price', 'Original Price', 'Discount', 'Stock', 'Lowest Price', 'Highest Price', 'Last Checked', 'Notes']

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Myntra Tracker Pro')
        self.resize(1100, 700)
        self.storage = ProductStorage()
        self.settings = self._load_settings()
        self._update_startup_setting()
        self.notifier = Notifier()
        self.products = self.storage.load_products()
        self.notes_by_url = self._load_notes()
        self.active_worker = None
        self._is_exiting = False
        self.tray_icon = None
        self._setup_interface()
        self._load_products()
        self._start_auto_refresh()

    def _setup_interface(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu('File')

        open_data_action = QAction('Open Data Folder', self)
        open_data_action.triggered.connect(self._open_data_folder)
        file_menu.addAction(open_data_action)

        backup_now_action = QAction('Backup Now', self)
        backup_now_action.triggered.connect(self.backup_now)
        file_menu.addAction(backup_now_action)

        restore_backup_action = QAction('Restore Backup', self)
        restore_backup_action.triggered.connect(self.restore_backup)
        file_menu.addAction(restore_backup_action)

        open_backup_folder_action = QAction('Open Backup Folder', self)
        open_backup_folder_action.triggered.connect(self.open_backup_folder)
        file_menu.addAction(open_backup_folder_action)

        open_logs_action = QAction('Open Logs Folder', self)
        open_logs_action.triggered.connect(self._open_logs_folder)
        file_menu.addAction(open_logs_action)

        view_logs_action = QAction('View Logs', self)
        view_logs_action.triggered.connect(self._show_logs_window)
        file_menu.addAction(view_logs_action)

        about_action = QAction('About', self)
        about_action.triggered.connect(self._show_about_dialog)
        file_menu.addAction(about_action)

        help_menu = menu_bar.addMenu('Help')
        check_updates_action = QAction('Check for Updates', self)
        check_updates_action.triggered.connect(self._show_update_dialog)
        help_menu.addAction(check_updates_action)

        main_layout = QVBoxLayout(central_widget)
        header_layout = QHBoxLayout()

        title = QLabel('Myntra Tracker Pro')
        title.setStyleSheet('font-size: 22px; font-weight: 600; padding: 4px;')
        header_layout.addWidget(title, alignment=Qt.AlignLeft)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('Paste Myntra product URL here')
        self.url_input.setMinimumWidth(400)
        self.url_input.returnPressed.connect(self.add_product)
        header_layout.addWidget(self.url_input)

        self.add_button = QPushButton('Add Product')
        self.add_button.clicked.connect(self.add_product)
        header_layout.addWidget(self.add_button)

        main_layout.addLayout(header_layout)

        dashboard_layout = QHBoxLayout()
        dashboard_layout.setSpacing(16)
        dashboard_layout.setContentsMargins(0, 12, 0, 12)

        self.dashboard_labels = {}
        for key, title_text in [
            ('total_products', 'Total Products'),
            ('in_stock', 'In Stock'),
            ('out_of_stock', 'Out of Stock'),
            ('average_discount', 'Average Discount'),
            ('biggest_discount', 'Biggest Discount'),
            ('price_drops_today', 'Price Drops Today'),
            ('favorites', 'Favorites'),
            ('target_price_reached', 'Target Price Reached'),
        ]:
            card_widget, value_label = self._create_dashboard_card(title_text)
            self.dashboard_labels[key] = value_label
            dashboard_layout.addWidget(card_widget)

        main_layout.addLayout(dashboard_layout)

        search_layout = QHBoxLayout()
        search_label = QLabel('Search Product:')
        search_label.setStyleSheet('font-size: 14px; padding: 4px;')
        search_layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Type to filter products...')
        self.search_input.textChanged.connect(self._filter_table_rows)
        search_layout.addWidget(self.search_input)

        filter_label = QLabel('Filter:')
        filter_label.setStyleSheet('font-size: 14px; padding: 4px; margin-left: 16px;')
        search_layout.addWidget(filter_label)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            'All Products',
            'In Stock',
            'Out of Stock',
            'Favorites',
            'Price Dropped Today',
            'Discount >= 50%',
            'Target Price Reached',
        ])
        self.filter_combo.currentIndexChanged.connect(self._filter_table_rows)
        search_layout.addWidget(self.filter_combo)

        theme_label = QLabel('Theme:')
        theme_label.setStyleSheet('font-size: 14px; padding: 4px; margin-left: 16px;')
        search_layout.addWidget(theme_label)

        self.theme_selector = QComboBox()
        self.theme_selector.addItems(['Dark', 'Light'])
        self.theme_selector.setCurrentText(self.settings.get('theme', 'Dark'))
        self.theme_selector.currentTextChanged.connect(self._on_theme_changed)
        search_layout.addWidget(self.theme_selector)

        main_layout.addLayout(search_layout)

        content_layout = QHBoxLayout()

        self.table = QTableWidget(0, len(self.COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(self.COLUMN_HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet(
            'QTableWidget { background-color: #1e1e1e; color: #f2f2f2; border: 1px solid #444; }'
            'QHeaderView::section { background-color: #2b2b2b; color: #f2f2f2; border: 1px solid #444; }'
        )
        self.table.cellDoubleClicked.connect(self._handle_table_double_click)
        self.table.cellClicked.connect(self._handle_table_cell_click)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self.table, 3)

        self.product_image_label = QLabel()
        self.product_image_label.setFixedSize(220, 220)
        self.product_image_label.setAlignment(Qt.AlignCenter)
        self.product_image_label.setPixmap(self._product_placeholder_pixmap())
        content_layout.addWidget(self.product_image_label)

        main_layout.addLayout(content_layout)

        button_layout = QHBoxLayout()
        self.delete_button = QPushButton('Delete Selected')
        self.delete_button.clicked.connect(self.delete_selected)
        button_layout.addWidget(self.delete_button)

        self.refresh_selected_button = QPushButton('Refresh Selected')
        self.refresh_selected_button.clicked.connect(self.refresh_selected)
        button_layout.addWidget(self.refresh_selected_button)

        self.refresh_all_button = QPushButton('Refresh All')
        self.refresh_all_button.clicked.connect(self.refresh_all)
        button_layout.addWidget(self.refresh_all_button)

        self.export_button = QPushButton('Export CSV')
        self.export_button.clicked.connect(self.export_csv)
        button_layout.addWidget(self.export_button)

        self.export_excel_button = QPushButton('Export Excel')
        self.export_excel_button.clicked.connect(self.export_excel)
        button_layout.addWidget(self.export_excel_button)

        self.import_button = QPushButton('Import CSV')
        self.import_button.clicked.connect(self.import_csv)
        button_layout.addWidget(self.import_button)

        self.history_button = QPushButton('Price History')
        self.history_button.clicked.connect(self.show_price_history)
        button_layout.addWidget(self.history_button)

        self.settings_button = QPushButton('Settings')
        self.settings_button.clicked.connect(self.show_settings_dialog)
        button_layout.addWidget(self.settings_button)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.next_refresh_label = QLabel('Auto Refresh: 05:00')
        self.next_refresh_label.setStyleSheet('color: #c8c8c8; padding-right: 12px;')
        self.last_refresh_label = QLabel('Last Refresh: N/A')
        self.last_refresh_label.setStyleSheet('color: #c8c8c8; padding-right: 12px;')
        self.selected_count_label = QLabel('Selected: 0')
        self.selected_count_label.setStyleSheet('color: #c8c8c8; padding-right: 12px;')
        self.status_bar.addPermanentWidget(self.last_refresh_label)
        self.status_bar.addPermanentWidget(self.next_refresh_label)
        self.status_bar.addPermanentWidget(self.selected_count_label)
        self.status_bar.showMessage('Ready')

        self._apply_styles()
        self._setup_system_tray()

    def _apply_styles(self) -> None:
        theme = self.settings.get('theme', 'Dark')
        if theme == 'Light':
            self.setStyleSheet(
                'QWidget { background-color: #f7f7f7; color: #202020; }'
                'QPushButton { background-color: #2d89ef; color: #ffffff; padding: 8px 14px; border-radius: 6px; }'
                'QPushButton:hover { background-color: #1e6fde; }'
                'QPushButton:disabled { background-color: #cccccc; color: #666666; }'
                'QLineEdit { background-color: #ffffff; border: 1px solid #cccccc; color: #202020; padding: 6px; border-radius: 6px; }'
                'QHeaderView::section { background-color: #e0e0e0; color: #202020; border: 1px solid #cccccc; }'
            )
        else:
            self.setStyleSheet(
                'QWidget { background-color: #121212; color: #e0e0e; }'
                'QPushButton { background-color: #2d89ef; color: #ffffff; padding: 8px 14px; border-radius: 6px; }'
                'QPushButton:hover { background-color: #1e6fde; }'
                'QPushButton:disabled { background-color: #444444; color: #999999; }'
                'QLineEdit { background-color: #1f1f1f; border: 1px solid #444444; color: #e0e0e0; padding: 6px; border-radius: 6px; }'
                'QHeaderView::section { border: 1px solid #3a3a3a; }'
            )

    def _create_dashboard_card(self, title_text: str):
        card = QWidget()
        card.setObjectName('dashboardCard')
        card.setStyleSheet(
            'QWidget#dashboardCard { background-color: #1f1f1f; border: 1px solid #333; border-radius: 12px; padding: 16px; }'
            'QLabel { color: #f2f2f2; }'
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(6)

        title_label = QLabel(title_text)
        title_label.setStyleSheet('font-size: 12px; color: #9aa5b1;')
        value_label = QLabel('0')
        value_label.setStyleSheet('font-size: 28px; font-weight: 700; color: #ffffff;')
        description_label = QLabel('')
        description_label.setStyleSheet('font-size: 11px; color: #7a8b9d;')
        description_label.setText('Updated after refresh')

        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        card_layout.addWidget(description_label)
        card_layout.addStretch()
        return card, value_label

    def _setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray_icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon = QSystemTrayIcon(tray_icon, self)
        tray_menu = QMenu(self)

        open_action = QAction('Open', self)
        open_action.triggered.connect(self._restore_from_tray)
        tray_menu.addAction(open_action)

        refresh_action = QAction('Refresh All', self)
        refresh_action.triggered.connect(self.refresh_all)
        tray_menu.addAction(refresh_action)

        tray_menu.addSeparator()

        exit_action = QAction('Exit', self)
        exit_action.triggered.connect(self._exit_app)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip('Myntra Tracker Pro')
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.show()

    def _restore_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _exit_app(self) -> None:
        self._is_exiting = True
        if self.tray_icon is not None:
            self.tray_icon.hide()
        QApplication.instance().quit()

    def _on_tray_icon_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._restore_from_tray()

    def _load_products(self) -> None:
        self.products = self.storage.load_products()
        self.notes_by_url = self._load_notes()
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for product in self.products:
            self._append_table_row(product)
        self._filter_table_rows()
        self._update_dashboard(True)
        self._update_selected_count()
        self.status_bar.showMessage(f'{len(self.products)} products loaded')

    def _update_dashboard(self, visible_only: bool = False) -> None:
        products = self._visible_products() if visible_only else self.products
        total_products = len(products)
        in_stock_count = sum(1 for product in products if product.get('stock', '').strip().lower() == 'in stock')
        out_of_stock_count = sum(1 for product in products if product.get('stock', '').strip().lower() == 'out of stock')
        favorites_count = sum(1 for product in products if bool(product.get('favorite', False)))
        price_drops_today = self._count_price_drops_today(filtered_products=products)
        target_price_reached = sum(
            1
            for product in products
            if self._is_target_price_reached(product)
        )
        average_discount = self._calculate_average_discount(products)
        biggest_discount = self._calculate_biggest_discount(products)

        self.dashboard_labels.get('total_products').setText(str(total_products))
        self.dashboard_labels.get('in_stock').setText(str(in_stock_count))
        self.dashboard_labels.get('out_of_stock').setText(str(out_of_stock_count))
        self.dashboard_labels.get('favorites').setText(str(favorites_count))
        self.dashboard_labels.get('price_drops_today').setText(str(price_drops_today))
        self.dashboard_labels.get('target_price_reached').setText(str(target_price_reached))
        self.dashboard_labels.get('average_discount').setText(f'{average_discount:.1f}%')
        self.dashboard_labels.get('biggest_discount').setText(f'{biggest_discount:.1f}%')

    def _count_price_drops_today(self, filtered_products: list[dict] | None = None) -> int:
        history_path = self.storage.base_path / 'data' / 'price_history.json'
        if not history_path.exists():
            return 0
        try:
            raw_text = history_path.read_text(encoding='utf-8')
            records = json.loads(raw_text or '[]')
        except Exception:
            return 0
        today = datetime.now().strftime('%Y-%m-%d')
        drops = 0
        by_url = {}
        for record in records:
            timestamp = record.get('timestamp', '')
            if not timestamp.startswith(today):
                continue
            url = record.get('url', '')
            if not url:
                continue
            price = self._parse_price_number(record.get('price', ''))
            if price is None:
                continue
            by_url.setdefault(url, []).append((timestamp, price))
        visible_urls = None
        if filtered_products is not None:
            visible_urls = {product.get('url', '') for product in filtered_products if product.get('url')}
        for url, prices in by_url.items():
            if visible_urls is not None and url not in visible_urls:
                continue
            prices.sort(key=lambda item: item[0])
            if len(prices) < 2:
                continue
            if prices[-1][1] < prices[-2][1]:
                drops += 1
        return drops

    def _calculate_average_discount(self, products: list[dict] | None = None) -> float:
        if products is None:
            products = self.products
        discounts = []
        for product in products:
            discount_value = self._parse_discount_value(product.get('discount', ''))
            if discount_value is not None:
                discounts.append(discount_value)
        if not discounts:
            return 0.0
        return sum(discounts) / len(discounts)

    def _calculate_biggest_discount(self, products: list[dict] | None = None) -> float:
        if products is None:
            products = self.products
        biggest = 0.0
        for product in products:
            discount_value = self._parse_discount_value(product.get('discount', ''))
            if discount_value is not None and discount_value > biggest:
                biggest = discount_value
        return biggest

    def _is_target_price_reached(self, product: dict) -> bool:
        current_price = self._parse_price_number(product.get('price', ''))
        target_price = self._parse_price_number(product.get('target_price', ''))
        if current_price is None or target_price is None or target_price <= 0:
            return False
        if current_price <= target_price:
            return True
        notes = self.notes_by_url.get(product.get('url', ''), '').strip().lower()
        return 'target price reached' in notes

    def _parse_discount_value(self, discount: str) -> Optional[float]:
        if not discount:
            return None
        numeric = ''.join(ch for ch in discount if ch.isdigit() or ch == '.')
        try:
            return float(numeric)
        except ValueError:
            return None

    def _create_thumbnail_label(self, image_url: str) -> QLabel:
        label = QLabel()
        label.setFixedSize(64, 64)
        label.setAlignment(Qt.AlignCenter)
        pixmap = self._load_thumbnail_pixmap(image_url)
        label.setPixmap(pixmap)
        return label

    def _image_cache_path(self, image_url: str) -> Path:
        cache_dir = self.storage.base_path / 'data' / 'cache' / 'images'
        cache_dir.mkdir(parents=True, exist_ok=True)
        if not image_url:
            return cache_dir / 'missing.jpg'
        match = re.search(r'\.(jpg|jpeg|png|gif|webp|bmp|svg)(?:[?&#]|$)', image_url, re.IGNORECASE)
        ext = f'.{match.group(1).lower()}' if match else '.jpg'
        url_hash = hashlib.sha256(image_url.encode('utf-8')).hexdigest()
        return cache_dir / f'{url_hash}{ext}'

    def _load_thumbnail_pixmap(self, image_url: str) -> QPixmap:
        pixmap = self._placeholder_pixmap()
        if not image_url:
            return pixmap
        cache_path = self._image_cache_path(image_url)
        loaded = QPixmap()
        if cache_path.exists() and loaded.load(str(cache_path)):
            return loaded.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        try:
            with urllib.request.urlopen(image_url, timeout=5) as response:
                data = response.read()
            if loaded.loadFromData(data):
                try:
                    cache_path.write_bytes(data)
                except Exception:
                    pass
                return loaded.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            pass
        return pixmap

    def _load_product_image_pixmap(self, image_url: str) -> QPixmap:
        pixmap = self._product_placeholder_pixmap()
        if not image_url:
            return pixmap
        cache_path = self._image_cache_path(image_url)
        loaded = QPixmap()
        if cache_path.exists() and loaded.load(str(cache_path)):
            return loaded.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        try:
            with urllib.request.urlopen(image_url, timeout=5) as response:
                data = response.read()
            if loaded.loadFromData(data):
                try:
                    cache_path.write_bytes(data)
                except Exception:
                    pass
                return loaded.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            pass
        return pixmap

    def _product_placeholder_pixmap(self) -> QPixmap:
        pixmap = QPixmap(220, 220)
        pixmap.fill(QColor('#2d2d2d'))
        return pixmap

    def _placeholder_pixmap(self) -> QPixmap:
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor('#2d2d2d'))
        return pixmap

    def _append_table_row(self, product: dict) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 70)

        image_label = self._create_thumbnail_label(product.get('image', ''))
        self.table.setCellWidget(row, 0, image_label)

        favorite_text = self._favorite_star(product.get('favorite', False))
        product_label = product.get('product', '')
        if self._is_lowest_ever_price(product):
            product_label = f'{product_label} 🔥 Lowest Ever'

        values = [
            product_label,
            favorite_text,
            product.get('brand', ''),
            product.get('price', ''),
            product.get('target_price', ''),
            product.get('original_price', ''),
            product.get('discount', ''),
            product.get('stock', ''),
            product.get('lowest_price', ''),
            product.get('highest_price', ''),
            product.get('last_checked', ''),
            self.notes_by_url.get(product.get('url', ''), ''),
        ]
        for column, text in enumerate(values, start=1):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            if column == 1:
                item.setData(Qt.UserRole, product.get('url', ''))
            if column == 2:
                item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, column, item)
        self._apply_row_background(row, product)

    def _find_product_index(self, url: str) -> int:
        for index, item in enumerate(self.products):
            if item.get('url') == url:
                return index
        return -1

    def _visible_products(self) -> list[dict]:
        visible = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            product_item = self.table.item(row, 1)
            url = product_item.data(Qt.UserRole) if product_item else ''
            if not url:
                continue
            product_index = self._find_product_index(url)
            if product_index != -1:
                visible.append(self.products[product_index])
        return visible

    def _filter_table_rows(self) -> None:
        query = self.search_input.text().strip().lower() if hasattr(self, 'search_input') else ''
        selected_filter = self.filter_combo.currentText() if hasattr(self, 'filter_combo') else 'All Products'
        price_drop_urls = self._price_drop_today_urls() if selected_filter == 'Price Dropped Today' else set()

        for row in range(self.table.rowCount()):
            search_match = self._row_matches_search(row, query)
            filter_match = self._row_matches_filter(row, selected_filter, price_drop_urls)
            visible = search_match and filter_match
            self.table.setRowHidden(row, not visible)
            self._set_row_search_highlight(row, search_match and bool(query))

        self._update_dashboard(True)

    def _row_matches_filter(self, row: int, selected_filter: str, price_drop_urls: set[str]) -> bool:
        if selected_filter == 'All Products':
            return True
        if selected_filter == 'Favorites':
            product_item = self.table.item(row, 1)
            url = product_item.data(Qt.UserRole) if product_item else ''
            if not url:
                return False
            product_index = self._find_product_index(url)
            if product_index == -1:
                return False
            return bool(self.products[product_index].get('favorite', False))
        stock_item = self.table.item(row, 8)
        stock_text = stock_item.text().strip().lower() if stock_item else ''
        if selected_filter == 'In Stock':
            return stock_text == 'in stock'
        if selected_filter == 'Out of Stock':
            return stock_text == 'out of stock'
        if selected_filter == 'Discount >= 50%':
            discount_item = self.table.item(row, 7)
            discount_text = discount_item.text() if discount_item else ''
            discount_value = self._parse_discount_value(discount_text)
            return discount_value is not None and discount_value >= 50
        if selected_filter == 'Price Dropped Today':
            product_item = self.table.item(row, 1)
            url = product_item.data(Qt.UserRole) if product_item else ''
            return url in price_drop_urls
        if selected_filter == 'Target Price Reached':
            product_item = self.table.item(row, 1)
            url = product_item.data(Qt.UserRole) if product_item else ''
            if not url:
                return False
            product_index = self._find_product_index(url)
            if product_index == -1:
                return False
            product = self.products[product_index]
            current_price = self._parse_price_number(product.get('price', ''))
            target_price = self._parse_price_number(product.get('target_price', ''))
            notes = self.notes_by_url.get(url, '').lower()
            if target_price is not None and target_price > 0 and current_price is not None and current_price <= target_price:
                return True
            return 'target price reached' in notes
        return True

    def _row_matches_search(self, row: int, query: str) -> bool:
        if not query:
            return True

        searchable_columns = [1, 3, 8, 12]
        for column in searchable_columns:
            item = self.table.item(row, column)
            if item and query in item.text().lower():
                return True

        product_item = self.table.item(row, 1)
        if product_item:
            url = str(product_item.data(Qt.UserRole) or '').lower()
            if query in url:
                return True

        return False

    def _set_row_search_highlight(self, row: int, highlight: bool) -> None:
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if not item:
                continue
            if highlight:
                item.setForeground(QBrush(QColor('#ffd54f')))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            else:
                item.setForeground(QBrush())
                font = item.font()
                font.setBold(False)
                item.setFont(font)

    def _apply_row_background(self, row: int, product: dict, price_drop: bool = False) -> None:
        if row < 0 or row >= self.table.rowCount():
            return

        current_price = self._parse_price_number(product.get('price', ''))
        target_price = self._parse_price_number(product.get('target_price', ''))
        target_reached = (
            target_price is not None
            and target_price > 0
            and current_price is not None
            and current_price <= target_price
        )
        if not target_reached:
            notes = self.notes_by_url.get(product.get('url', ''), '').strip().lower()
            target_reached = 'target price reached' in notes

        if target_reached:
            color = QColor('#d4f7dc')
        elif price_drop:
            color = QColor('#fff3b0')
        elif product.get('stock', '').strip().lower() == 'out of stock':
            color = QColor('#f8d7da')
        elif bool(product.get('favorite', False)):
            color = QColor('#d6e9ff')
        else:
            color = None

        brush = QBrush(color) if color else QBrush()
        style = f'background-color: {color.name()};' if color else ''

        widget = self.table.cellWidget(row, 0)
        if widget is not None:
            widget.setStyleSheet(style)

        for column in range(1, self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                item.setBackground(brush)

    def _price_drop_today_urls(self) -> set[str]:
        history_path = self.storage.base_path / 'data' / 'price_history.json'
        if not history_path.exists():
            return set()
        try:
            raw_text = history_path.read_text(encoding='utf-8')
            records = json.loads(raw_text or '[]')
        except Exception:
            return set()

        today = datetime.now().strftime('%Y-%m-%d')
        by_url = {}
        for record in records:
            timestamp = record.get('timestamp', '')
            if not timestamp.startswith(today):
                continue
            url = record.get('url', '')
            if not url:
                continue
            price = self._parse_price_number(record.get('price', ''))
            if price is None:
                continue
            by_url.setdefault(url, []).append((timestamp, price))

        dropped_urls = set()
        for url, prices in by_url.items():
            prices.sort(key=lambda item: item[0])
            if len(prices) >= 2 and prices[-1][1] < prices[-2][1]:
                dropped_urls.add(url)
        return dropped_urls

    def _find_table_row(self, url: str) -> int:
        for row in range(self.table.rowCount()):
            product_name = self.table.item(row, 1)
            if product_name and product_name.data(Qt.UserRole) == url:
                return row
        return -1

    def _on_selection_changed(self, selected, deselected) -> None:
        self._update_selected_count()
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            self.product_image_label.setPixmap(self._product_placeholder_pixmap())
            return
        row = selected_rows[0].row()
        product_item = self.table.item(row, 1)
        url = product_item.data(Qt.UserRole) if product_item else ''
        if not url:
            self.product_image_label.setPixmap(self._product_placeholder_pixmap())
            return
        product_index = self._find_product_index(url)
        if product_index == -1:
            self.product_image_label.setPixmap(self._product_placeholder_pixmap())
            return
        image_url = self.products[product_index].get('image', '')
        self.product_image_label.setPixmap(self._load_product_image_pixmap(image_url))

    def _update_selected_count(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        self.selected_count_label.setText(f'Selected: {len(selected_rows)}')

    def _handle_table_double_click(self, row: int, column: int) -> None:
        if column == 5:
            self._edit_target_price(row)
            return
        if column == 12:
            self._edit_notes(row)
            return

        product_item = self.table.item(row, 1)
        url = product_item.data(Qt.UserRole) if product_item else ''
        if not url and row < len(self.products):
            url = self.products[row].get('url', '')
        if url:
            webbrowser.open(url)

    def _handle_table_cell_click(self, row: int, column: int) -> None:
        if column != 2:
            return
        product_item = self.table.item(row, 1)
        url = product_item.data(Qt.UserRole) if product_item else ''
        if not url:
            return
        product_index = self._find_product_index(url)
        if product_index == -1:
            return
        current_favorite = bool(self.products[product_index].get('favorite', False))
        self.products[product_index]['favorite'] = not current_favorite
        self.storage.save_products(self.products)
        self._update_table_row(self.products[product_index], row)
        self._filter_table_rows()

    def _favorite_star(self, favorite_value: bool) -> str:
        return '★' if bool(favorite_value) else '☆'

    def _edit_notes(self, row: int) -> None:
        product_item = self.table.item(row, 1)
        url = product_item.data(Qt.UserRole) if product_item else ''
        if not url:
            return

        current_note = self.notes_by_url.get(url, '')
        new_text, ok = QInputDialog.getText(self, 'Edit Notes', 'Notes:', QLineEdit.Normal, current_note)
        if not ok:
            return

        self.notes_by_url[url] = new_text.strip()
        self._save_notes()
        item = self.table.item(row, 12)
        if item is None:
            item = QTableWidgetItem(self.notes_by_url[url])
            self.table.setItem(row, 12, item)
        else:
            item.setText(self.notes_by_url[url])
        self.status_bar.showMessage('Notes saved')

    def _notes_file_path(self) -> Path:
        notes_file = self.storage.base_path / 'data' / 'notes.json'
        notes_file.parent.mkdir(parents=True, exist_ok=True)
        return notes_file

    def _load_notes(self) -> dict:
        notes_file = self._notes_file_path()
        if not notes_file.exists():
            return {}
        try:
            raw_text = notes_file.read_text(encoding='utf-8')
            data = json.loads(raw_text or '{}')
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            logging.exception('Unable to load notes')
        return {}

    def _save_notes(self) -> None:
        try:
            notes_file = self._notes_file_path()
            notes_file.write_text(json.dumps(self.notes_by_url, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            logging.exception('Unable to save notes')

    def _edit_target_price(self, row: int) -> None:
        item = self.table.item(row, 5)
        current_value = item.text() if item else ''
        new_text, ok = QInputDialog.getText(self, 'Edit Target Price', 'Target Price:', QLineEdit.Normal, current_value)
        if not ok:
            return
        value = new_text.strip()
        if not value:
            return
        if not re.fullmatch(r'\d+(?:\.\d{1,2})?', value):
            QMessageBox.warning(self, 'Invalid Value', 'Please enter only numeric values for Target Price.')
            return
        formatted = f'₹{value}' if not value.startswith('₹') else value
        if item is None:
            item = QTableWidgetItem(formatted)
            self.table.setItem(row, 4, item)
        else:
            item.setText(formatted)
        if row < len(self.products):
            product = self.products[row]
            product['target_price'] = formatted
            self.storage.save_products(self.products)
        self.status_bar.showMessage('Target price updated')

    def _update_table_row(self, product: dict, row: int) -> None:
        image_label = self._create_thumbnail_label(product.get('image', ''))
        self.table.setCellWidget(row, 0, image_label)

        favorite_text = self._favorite_star(product.get('favorite', False))
        product_label = product.get('product', '')
        if self._is_lowest_ever_price(product):
            product_label = f'{product_label} 🔥 Lowest Ever'

        values = [
            product_label,
            favorite_text,
            product.get('brand', ''),
            product.get('price', ''),
            product.get('target_price', ''),
            product.get('original_price', ''),
            product.get('discount', ''),
            product.get('stock', ''),
            product.get('lowest_price', ''),
            product.get('highest_price', ''),
            product.get('last_checked', ''),
            self.notes_by_url.get(product.get('url', ''), ''),
        ]
        for column, text in enumerate(values, start=1):
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem(text)
                self.table.setItem(row, column, item)
            else:
                item.setText(text)
            if column == 2:
                item.setTextAlignment(Qt.AlignCenter)
            else:
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            if column == 1:
                item.setData(Qt.UserRole, product.get('url', ''))
        self._apply_row_background(row, product)

    def add_product(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, 'Validation Error', 'Please paste a Myntra product URL.')
            return
        if 'myntra.com' not in url.lower():
            QMessageBox.warning(self, 'Validation Error', 'The URL does not appear to be a Myntra product link.')
            return
        if any(item.get('url') == url for item in self.products):
            QMessageBox.information(self, 'Already Exists', 'This product is already being tracked.')
            return
        new_product = self.storage.create_empty_product(url)
        self.products.append(new_product)
        self.storage.save_products(self.products)
        self._append_table_row(new_product)
        self.url_input.clear()
        self.status_bar.showMessage('Product added. Refreshing information...')
        self.refresh_products([new_product])

    def delete_selected(self) -> None:
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        if not selected_rows:
            QMessageBox.information(self, 'Nothing Selected', 'Please select at least one row to delete.')
            return
        for row in selected_rows:
            url = self.table.item(row, 1).data(Qt.UserRole) if self.table.item(row, 1) else ''
            if not url:
                url = self.products[row].get('url', '')
            self.products = [item for item in self.products if item.get('url') != url]
            self.table.removeRow(row)
        self.storage.save_products(self.products)
        self.status_bar.showMessage('Selected products removed')

    def refresh_selected(self) -> None:
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected_rows:
            QMessageBox.information(self, 'Nothing Selected', 'Select a product row to refresh.')
            return
        products_to_refresh = []
        for row in selected_rows:
            url = self.table.item(row, 1).data(Qt.UserRole) if self.table.item(row, 1) else ''
            if not url and row < len(self.products):
                url = self.products[row].get('url', '')
            if url:
                product_index = self._find_product_index(url)
                if product_index != -1:
                    products_to_refresh.append(self.products[product_index])
        self.refresh_products(products_to_refresh)

    def refresh_all(self) -> None:
        if not self.products:
            self.status_bar.showMessage('No products to refresh')
            return
        self.refresh_products(self.products)

    def export_csv(self) -> None:
        if not self.products:
            QMessageBox.information(self, 'No Products', 'There are no products to export.')
            return
        file_path, _ = QFileDialog.getSaveFileName(self, 'Export Products to CSV', 'myntra_products.csv', 'CSV Files (*.csv)')
        if not file_path:
            return
        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(self.COLUMN_HEADERS + ['URL'])
                for product in self.products:
                    writer.writerow([
                        product.get('product', ''),
                        '★' if product.get('favorite', False) else '☆',
                        product.get('brand', ''),
                        product.get('price', ''),
                        product.get('original_price', ''),
                        product.get('discount', ''),
                        product.get('stock', ''),
                        product.get('last_checked', ''),
                        product.get('url', ''),
                    ])
            self.status_bar.showMessage(f'Exported {len(self.products)} products to CSV')
        except Exception:
            logging.exception('Unable to export CSV')
            QMessageBox.critical(self, 'Export Failed', 'Unable to write the CSV file.')

    def export_excel(self) -> None:
        if not self.products:
            QMessageBox.information(self, 'No Products', 'There are no products to export.')
            return
        file_path, _ = QFileDialog.getSaveFileName(self, 'Export Products to Excel', 'myntra_products.xlsx', 'Excel Files (*.xlsx)')
        if not file_path:
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            logging.exception('openpyxl is not installed')
            QMessageBox.critical(self, 'Export Failed', 'openpyxl is required to export Excel files.')
            return

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Products'
        headers = ['Product', 'Favorite', 'Brand', 'Price', 'Original Price', 'Discount', 'Stock', 'Last Checked', 'URL']
        sheet.append(headers)
        for product in self.products:
            sheet.append([
                product.get('product', ''),
                'Yes' if product.get('favorite', False) else 'No',
                product.get('brand', ''),
                product.get('price', ''),
                product.get('original_price', ''),
                product.get('discount', ''),
                product.get('stock', ''),
                product.get('last_checked', ''),
                product.get('url', ''),
            ])
        try:
            workbook.save(file_path)
            self.status_bar.showMessage(f'Exported {len(self.products)} products to Excel')
        except Exception:
            logging.exception('Unable to export Excel file')
            QMessageBox.critical(self, 'Export Failed', 'Unable to write the Excel file.')

    def import_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, 'Import Products from CSV', '', 'CSV Files (*.csv)')
        if not file_path:
            return

        try:
            with open(file_path, 'r', newline='', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                existing_urls = {product.get('url', '').strip().lower() for product in self.products if product.get('url')}
                imported_urls = set()
                imported_count = 0
                for row in reader:
                    url = ''
                    for key in row:
                        if key.strip().lower() == 'url':
                            url = (row[key] or '').strip()
                            break
                    if not url:
                        continue
                    normalized_url = url.lower()
                    if 'myntra.com' not in normalized_url or not normalized_url.startswith(('http://', 'https://')):
                        continue
                    if normalized_url in existing_urls or normalized_url in imported_urls:
                        continue
                    product = self.storage.create_empty_product(url)
                    self.products.append(product)
                    imported_urls.add(normalized_url)
                    imported_count += 1
                if imported_count:
                    self.storage.save_products(self.products)
                    self._refresh_table()
                QMessageBox.information(self, 'Import Complete', f'Imported {imported_count} products.')
        except Exception:
            logging.exception('Unable to import CSV')
            QMessageBox.critical(self, 'Import Failed', 'Unable to read the CSV file.')

    def show_price_history(self) -> None:
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected_rows:
            QMessageBox.information(self, 'No Selection', 'Please select a product.')
            return
        row = selected_rows[0]
        product_item = self.table.item(row, 1)
        url = product_item.data(Qt.UserRole) if product_item else ''
        if not url:
            QMessageBox.warning(self, 'Missing URL', 'Selected product does not have a valid URL.')
            return

        history_path = self.storage.base_path / 'data' / 'price_history.json'
        if not history_path.exists():
            QMessageBox.information(self, 'No History', 'No price history available.')
            return

        try:
            raw_text = history_path.read_text(encoding='utf-8')
            history_data = json.loads(raw_text or '[]')
        except Exception:
            logging.exception('Unable to read price history')
            QMessageBox.critical(self, 'Error', 'Unable to load price history.')
            return

        product_history = [record for record in history_data if record.get('url') == url]
        if not product_history:
            QMessageBox.information(self, 'No History', 'No price history available.')
            return

        parsed_history = []
        for record in product_history:
            timestamp = record.get('timestamp', '')
            price_value = self._parse_price_number(record.get('price', ''))
            if not timestamp or price_value is None:
                continue
            try:
                parsed_history.append((datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S'), price_value, timestamp))
            except ValueError:
                continue

        if not parsed_history:
            QMessageBox.information(self, 'No History', 'No price history available.')
            return

        parsed_history.sort(key=lambda item: item[0])
        dates = [item[0] for item in parsed_history]
        prices = [item[1] for item in parsed_history]
        labels = [item[2] for item in parsed_history]

        lowest_index = min(range(len(prices)), key=lambda i: prices[i])
        highest_index = max(range(len(prices)), key=lambda i: prices[i])
        product_name = self.table.item(row, 1).text() if self.table.item(row, 1) else 'Product'

        dialog = QDialog(self)
        dialog.setWindowTitle('Price History')
        dialog.resize(780, 520)

        figure = Figure(figsize=(7, 4), dpi=120)
        canvas = FigureCanvas(figure)
        axis = figure.add_subplot(111)
        line, = axis.plot(dates, prices, marker='o', linestyle='-', color='#2d89ef', linewidth=2, markersize=6, picker=5, antialiased=True)

        lowest_price = prices[lowest_index]
        highest_price = prices[highest_index]
        current_price = prices[-1]
        has_range = lowest_price != highest_price

        if has_range:
            axis.scatter([dates[lowest_index]], [lowest_price], color='green', s=100, zorder=5, label='Lowest')
            axis.scatter([dates[highest_index]], [highest_price], color='red', s=100, zorder=5, label='Highest')
            axis.axhline(lowest_price, color='green', linestyle='--', linewidth=1, alpha=0.7)
            axis.axhline(highest_price, color='red', linestyle='--', linewidth=1, alpha=0.7)
        else:
            axis.scatter([dates[lowest_index]], [lowest_price], color='purple', s=100, zorder=5, label='Lowest = Highest')
            axis.axhline(lowest_price, color='purple', linestyle='--', linewidth=1, alpha=0.7)

        for x, y in zip(dates, prices):
            axis.text(x, y, f'₹{y:.2f}', fontsize=8, ha='center', va='bottom', color='#ffffff', backgroundcolor='black', alpha=0.75)

        axis.set_title(f'{product_name}\nPrice History')
        axis.set_xlabel('Date/Time')
        axis.set_ylabel('Price (₹)')
        axis.grid(True, alpha=0.3)

        stats_text = (
            f'Current Price: ₹{current_price:.2f}\n'
            f'Lowest Price: ₹{lowest_price:.2f}\n'
            f'Highest Price: ₹{highest_price:.2f}'
        )
        axis.text(
            0.02,
            0.98,
            stats_text,
            transform=axis.transAxes,
            fontsize=9,
            va='top',
            ha='left',
            bbox=dict(facecolor='#1e1e1e', alpha=0.85, edgecolor='#888888', boxstyle='round,pad=0.6'),
        )

        if has_range:
            axis.legend(loc='best')
        else:
            axis.legend(loc='best')

        axis.xaxis.set_major_locator(mdates.AutoDateLocator())
        axis.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        for label in axis.get_xticklabels():
            label.set_rotation(45)
            label.set_ha('right')

        figure.tight_layout()

        annot = axis.annotate(
            '',
            xy=(0, 0),
            xytext=(15, 15),
            textcoords='offset points',
            bbox=dict(boxstyle='round', fc='w', alpha=0.9),
            arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.2'),
        )
        annot.set_visible(False)

        def update_annot(ind):
            idx = ind['ind'][0]
            x = dates[idx]
            y = prices[idx]
            annot.xy = (x, y)
            date_text = x.strftime('%Y-%m-%d')
            time_text = x.strftime('%H:%M:%S')
            annot.set_text(f'Date: {date_text}\nTime: {time_text}\nPrice: ₹{y:.2f}')
            annot.get_bbox_patch().set_alpha(0.9)

        def hover(event):
            if event.inaxes == axis:
                cont, ind = line.contains(event)
                if cont:
                    update_annot(ind)
                    annot.set_visible(True)
                    canvas.draw_idle()
                else:
                    if annot.get_visible():
                        annot.set_visible(False)
                        canvas.draw_idle()

        canvas.mpl_connect('motion_notify_event', hover)

        layout = QVBoxLayout(dialog)
        layout.addWidget(canvas)
        dialog.setLayout(layout)
        dialog.exec()

    def show_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle('Settings')
        dialog.resize(420, 320)

        refresh_combo = QComboBox()
        refresh_combo.addItems(['1 Minute', '5 Minutes', '10 Minutes', '30 Minutes', '1 Hour'])
        interval_index = {
            1: 0,
            5: 1,
            10: 2,
            30: 3,
            60: 4,
        }.get(self.settings.get('refresh_interval_minutes', 5), 1)
        refresh_combo.setCurrentIndex(interval_index)

        price_notifications_checkbox = QCheckBox('Enable Price Notifications')
        price_notifications_checkbox.setChecked(self.settings.get('enable_price_notifications', True))
        stock_notifications_checkbox = QCheckBox('Enable Stock Notifications')
        stock_notifications_checkbox.setChecked(self.settings.get('enable_stock_notifications', True))
        startup_checkbox = QCheckBox('Start Myntra Tracker when Windows starts')
        startup_checkbox.setChecked(self.settings.get('start_with_windows', False))

        theme_combo = QComboBox()
        theme_combo.addItems(['Dark', 'Light'])
        theme_combo.setCurrentText(self.settings.get('theme', 'Dark'))

        form_layout = QFormLayout()
        form_layout.addRow('Refresh Interval', refresh_combo)
        form_layout.addRow(price_notifications_checkbox)
        form_layout.addRow(stock_notifications_checkbox)
        form_layout.addRow(startup_checkbox)
        form_layout.addRow('Theme', theme_combo)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(lambda: self._save_settings_dialog(dialog, refresh_combo, price_notifications_checkbox, stock_notifications_checkbox, startup_checkbox, theme_combo))
        button_box.rejected.connect(dialog.reject)

        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.addLayout(form_layout)
        dialog_layout.addWidget(button_box)
        dialog.setLayout(dialog_layout)
        dialog.exec()

    def _settings_file_path(self) -> Path:
        settings_file = self.storage.base_path / 'data' / 'settings.json'
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        return settings_file

    def _default_settings(self) -> dict:
        return {
            'refresh_interval_minutes': 5,
            'enable_price_notifications': True,
            'enable_stock_notifications': True,
            'start_with_windows': False,
            'theme': 'Dark',
        }

    def _load_settings(self) -> dict:
        settings_file = self._settings_file_path()
        if not settings_file.exists():
            return self._default_settings()
        try:
            raw_text = settings_file.read_text(encoding='utf-8')
            data = json.loads(raw_text or '{}')
            if not isinstance(data, dict):
                return self._default_settings()
            settings = self._default_settings()
            settings.update(data)
            return settings
        except Exception:
            logging.exception('Unable to load settings')
            return self._default_settings()

    def _save_settings(self) -> None:
        try:
            settings_file = self._settings_file_path()
            settings_file.write_text(json.dumps(self.settings, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            logging.exception('Unable to save settings')

    def _add_startup_registry_entry(self) -> None:
        if winreg is None:
            return
        try:
            command = self._startup_command()
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run',
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, 'MyntraTrackerPro', 0, winreg.REG_SZ, command)
        except OSError:
            logging.exception('Unable to add startup registry entry')

    def _remove_startup_registry_entry(self) -> None:
        if winreg is None:
            return
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run',
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, 'MyntraTrackerPro')
        except FileNotFoundError:
            pass
        except OSError:
            logging.exception('Unable to remove startup registry entry')

    def _startup_command(self) -> str:
        app_path = Path(__file__).resolve().parent / 'app.py'
        if app_path.exists():
            return f'"{sys.executable}" "{app_path}"'
        return f'"{sys.executable}"'

    def _update_startup_setting(self) -> None:
        if self.settings.get('start_with_windows', False):
            self._add_startup_registry_entry()
        else:
            self._remove_startup_registry_entry()

    def _update_refresh_interval(self) -> None:
        self.refresh_interval_seconds = self.settings.get('refresh_interval_minutes', 5) * 60
        if hasattr(self, 'auto_refresh_timer'):
            self.auto_refresh_timer.setInterval(self.refresh_interval_seconds * 1000)
        self._reset_countdown()

    def _on_theme_changed(self, theme: str) -> None:
        if theme not in ('Dark', 'Light'):
            return
        self.settings['theme'] = theme
        self._apply_styles()
        self._save_settings()

    def _open_data_folder(self) -> None:
        data_folder = self.storage.base_path / 'data'
        data_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_folder)))

    def _open_logs_folder(self) -> None:
        logs_folder = self.storage.base_path / 'logs'
        logs_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_folder)))

    def open_backup_folder(self) -> None:
        backup_folder = self.storage.base_path / 'backups'
        backup_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(backup_folder)))

    def backup_now(self) -> None:
        backup_root = self.storage.base_path / 'backups'
        backup_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_folder = backup_root / f'backup_{timestamp}'
        try:
            shutil.copytree(self.storage.base_path / 'data', backup_folder)
            QMessageBox.information(self, 'Backup Created', f'Backup created: {backup_folder.name}')
            logging.info('Backup created: %s', backup_folder)
        except Exception:
            logging.exception('Backup failed')
            QMessageBox.critical(self, 'Backup Failed', 'Unable to create a backup. See logs for details.')

    def restore_backup(self) -> None:
        backup_root = self.storage.base_path / 'backups'
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_folder = QFileDialog.getExistingDirectory(self, 'Select Backup Folder', str(backup_root))
        if not backup_folder:
            return
        backup_path = Path(backup_folder)
        if not backup_path.exists() or not backup_path.is_dir():
            QMessageBox.warning(self, 'Invalid Backup', 'The selected folder is not a valid backup.')
            return
        confirm = QMessageBox.question(
            self,
            'Confirm Restore',
            f'Restore backup from {backup_path.name}? This will overwrite current product data.',
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        data_folder = self.storage.base_path / 'data'
        try:
            if data_folder.exists():
                shutil.rmtree(data_folder)
            shutil.copytree(backup_path, data_folder)
            self._load_products()
            QMessageBox.information(self, 'Restore Completed', 'Backup restored successfully.')
            logging.info('Backup restored from %s', backup_path)
        except Exception:
            logging.exception('Restore failed')
            QMessageBox.critical(self, 'Restore Failed', 'Unable to restore the selected backup. See logs for details.')
        if not backups:
            QMessageBox.information(self, 'No Backups', 'No backups are available to restore.')
            return

        backup_names = [backup.name for backup in backups]
        selected_backup, ok = QInputDialog.getItem(
            self,
            'Restore Backup',
            'Select a backup to restore:',
            backup_names,
            0,
            False,
        )
        if not ok or not selected_backup:
            return

        confirm = QMessageBox.question(
            self,
            'Confirm Restore',
            f'Restore backup {selected_backup}? This will overwrite current products and price history.',
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            backup_path = next(backup for backup in backups if backup.name == selected_backup)
            self.storage.restore_backup(backup_path)
            self._load_products()
            QMessageBox.information(self, 'Restore Completed', 'Backup restored successfully.')
            logging.info('Restored backup %s', backup_path)
        except Exception:
            logging.exception('Restore failed')
            QMessageBox.critical(self, 'Restore Failed', 'Unable to restore the selected backup. See logs for details.')

    def _show_logs_window(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle('Logs')
        dialog.resize(760, 520)

        layout = QVBoxLayout(dialog)
        logs_text_edit = QTextEdit()
        logs_text_edit.setReadOnly(True)
        layout.addWidget(logs_text_edit)

        button_box = QDialogButtonBox()
        refresh_button = QPushButton('Refresh')
        clear_button = QPushButton('Clear Logs')
        button_box.addButton(refresh_button, QDialogButtonBox.ActionRole)
        button_box.addButton(clear_button, QDialogButtonBox.ActionRole)
        refresh_button.clicked.connect(lambda: self._load_logs_into_text_edit(logs_text_edit))
        clear_button.clicked.connect(lambda: self._clear_logs(logs_text_edit))
        layout.addWidget(button_box)

        self._load_logs_into_text_edit(logs_text_edit)
        dialog.exec()

    def _show_about_dialog(self) -> None:
        try:
            import playwright
        except Exception:
            playwright_version = 'Unknown'
        else:
            playwright_version = getattr(playwright, '__version__', 'Unknown')

        about_text = (
            '<h2>Myntra Tracker Pro</h2>'
            f'<p><b>Version:</b> 1.0.0</p>'
            f'<p><b>Python Version:</b> {sys.version.split()[0]}</p>'
            f'<p><b>Playwright Version:</b> {playwright_version}</p>'
            '<p><b>Developer:</b> Myntra Tracker Pro Team</p>'
            '<p><b>License:</b> MIT License</p>'
        )

        dialog = QDialog(self)
        dialog.setWindowTitle('About')
        dialog.resize(420, 280)

        layout = QVBoxLayout(dialog)
        label = QLabel(about_text)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        dialog.exec()

    def _show_update_dialog(self) -> None:
        current_version = '1.0.0'
        latest_version = '1.0.1'
        dialog = QDialog(self)
        dialog.setWindowTitle('Check for Updates')
        dialog.resize(420, 260)

        layout = QVBoxLayout(dialog)
        update_text = (
            '<h2>Check for Updates</h2>'
            f'<p><b>Current Version:</b> {current_version}</p>'
            f'<p><b>Latest Version:</b> {latest_version}</p>'
        )
        label = QLabel(update_text)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        if latest_version != current_version:
            download_button = QPushButton('Download Update')
            download_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://example.com/myntra-tracker-pro/download')))
            button_box.addButton(download_button, QDialogButtonBox.ActionRole)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        dialog.exec()

    def _load_logs_into_text_edit(self, text_edit: QTextEdit) -> None:
        logs_file = self._logs_file_path()
        if not logs_file.exists():
            text_edit.setPlainText('No logs available.')
            return
        try:
            log_contents = logs_file.read_text(encoding='utf-8') or 'No logs available.'
            text_edit.setPlainText(log_contents)
        except Exception:
            logging.exception('Unable to load logs')
            text_edit.setPlainText('Unable to load logs.')

    def _clear_logs(self, text_edit: QTextEdit) -> None:
        logs_file = self._logs_file_path()
        try:
            logs_file.write_text('', encoding='utf-8')
            text_edit.setPlainText('')
        except Exception:
            logging.exception('Unable to clear logs')
            QMessageBox.critical(self, 'Clear Failed', 'Unable to clear the logs file.')

    def _logs_file_path(self) -> Path:
        logs_folder = self.storage.base_path / 'logs'
        logs_folder.mkdir(parents=True, exist_ok=True)
        return logs_folder / 'app.log'

    def _save_settings_dialog(
        self,
        dialog: QDialog,
        refresh_combo: QComboBox,
        price_notifications_checkbox: QCheckBox,
        stock_notifications_checkbox: QCheckBox,
        startup_checkbox: QCheckBox,
        theme_combo: QComboBox,
    ) -> None:
        interval_text = refresh_combo.currentText()
        if interval_text.startswith('1 Hour'):
            refresh_interval_minutes = 60
        elif interval_text.startswith('30'):
            refresh_interval_minutes = 30
        elif interval_text.startswith('10'):
            refresh_interval_minutes = 10
        elif interval_text.startswith('5'):
            refresh_interval_minutes = 5
        else:
            refresh_interval_minutes = 1

        self.settings = {
            'refresh_interval_minutes': refresh_interval_minutes,
            'enable_price_notifications': price_notifications_checkbox.isChecked(),
            'enable_stock_notifications': stock_notifications_checkbox.isChecked(),
            'start_with_windows': startup_checkbox.isChecked(),
            'theme': theme_combo.currentText(),
        }
        self._save_settings()
        self._update_startup_setting()
        self._apply_styles()
        self._update_refresh_interval()
        dialog.accept()

    def refresh_products(self, products: list[dict]) -> None:
        if self.active_worker is not None and self.active_worker.isRunning():
            QMessageBox.information(self, 'Refresh In Progress', 'A refresh is already running. Please wait.')
            return
        self.active_worker = RefreshWorker(products)
        self.active_worker.product_updated.connect(self._on_product_updated)
        self.active_worker.change_signal.connect(self._on_worker_change)
        self.active_worker.target_price_reached.connect(self._on_target_price_reached)
        self.active_worker.error.connect(self._on_worker_error)
        self.active_worker.finished.connect(self._on_refresh_finished)
        self._set_refresh_buttons_enabled(False)
        self.status_bar.showMessage('Refreshing...')
        self.active_worker.start()

    def _on_product_updated(self, updated: dict) -> None:
        if not updated:
            return
        url = updated.get('url', '')
        index = self._find_product_index(url)
        if index >= 0:
            existing = self.products[index].copy()
            self.products[index].update(updated)
        else:
            existing = {k: '' for k in self.storage.DEFAULT_FIELDS}
            self.products.append(updated)
            index = len(self.products) - 1
        self.storage.save_products(self.products)
        self._refresh_table()
        self._highlight_row_changes(index, existing, updated)
        self._notify_changes(existing, updated)

    def _notify_changes(self, old: dict, new: dict) -> None:
        old_price = old.get('price', '')
        new_price = new.get('price', '')
        old_price_value = self._parse_price_number(old_price)
        new_price_value = self._parse_price_number(new_price)
        if (
            old_price_value is not None
            and new_price_value is not None
            and new_price_value < old_price_value
            and self.settings.get('enable_price_notifications', True)
        ):
            self.notifier.notify_price_change(
                new.get('product', 'Product'),
                f'{old_price_value:.2f}',
                f'{new_price_value:.2f}',
            )
        old_stock = old.get('stock', '')
        new_stock = new.get('stock', '')
        if (
            old_stock == 'Out of Stock'
            and new_stock == 'In Stock'
            and self.settings.get('enable_stock_notifications', True)
        ):
            self.notifier.notify_stock_change(new.get('product', 'Product'))
        lowest_price_value = self._parse_price_number(new.get('lowest_price', ''))
        if (
            self.settings.get('enable_price_notifications', True)
            and new_price_value is not None
            and lowest_price_value is not None
            and new_price_value == lowest_price_value
            and self._parse_price_number(old_price) != new_price_value
        ):
            self.notifier.notify(
                'Lowest Price Ever',
                f"{new.get('product', 'Product')}\n{new_price}",
            )

    def _highlight_row_changes(self, row: int, old: dict, new: dict) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        old_price = old.get('price', '')
        new_price = new.get('price', '')
        price_drop = False
        if old_price and new_price:
            old_value = self._parse_price_number(old_price)
            new_value = self._parse_price_number(new_price)
            if old_value is not None and new_value is not None and new_value < old_value:
                price_drop = True
        self._apply_row_background(row, new, price_drop=price_drop)

    def _parse_price_number(self, price: str) -> Optional[float]:
        if not price:
            return None
        numeric = re.sub(r'[^\d.]', '', price)
        try:
            return float(numeric)
        except ValueError:
            return None

    def _is_lowest_ever_price(self, product: dict) -> bool:
        current_price = self._parse_price_number(product.get('price', ''))
        lowest_price = self._parse_price_number(product.get('lowest_price', ''))
        if current_price is None or lowest_price is None:
            return False
        return current_price == lowest_price

    def _on_worker_change(self, change: tuple) -> None:
        pass

    def _on_worker_error(self, message: str) -> None:
        logging.warning(message)
        self.status_bar.showMessage(message)

    def _on_target_price_reached(self, updated: dict) -> None:
        product_name = updated.get('product', 'Product')
        current_price = self._parse_price_number(updated.get('price', ''))
        target_price = self._parse_price_number(updated.get('target_price', ''))
        if current_price is None or target_price is None:
            return
        price_text = f'{current_price:.2f}'.rstrip('0').rstrip('.')
        target_text = f'{target_price:.2f}'.rstrip('0').rstrip('.')
        self.notifier.notify_target_price_reached(product_name, price_text, target_text)

        url = updated.get('url', '')
        self.notes_by_url[url] = 'Target Price Reached'
        self._save_notes()
        row = self._find_table_row(url)
        if row != -1:
            self._apply_row_background(row, updated)
            notes_item = self.table.item(row, 12)
            if notes_item is None:
                notes_item = QTableWidgetItem(self.notes_by_url[url])
                self.table.setItem(row, 12, notes_item)
            else:
                notes_item.setText(self.notes_by_url[url])
        logging.info('Target price reached for %s at %s (target %s)', product_name, price_text, target_text)
        self.status_bar.showMessage('Target price reached.')

    def _on_refresh_finished(self) -> None:
        self._set_refresh_buttons_enabled(True)
        self.status_bar.showMessage('Ready')
        self.last_refresh_label.setText(f'Last Refresh: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        self._update_selected_count()
        self.active_worker = None

    def _set_refresh_buttons_enabled(self, enabled: bool) -> None:
        self.refresh_selected_button.setEnabled(enabled)
        self.refresh_all_button.setEnabled(enabled)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self.add_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.refresh_selected_button.setEnabled(enabled)
        self.refresh_all_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)

    def _start_auto_refresh(self) -> None:
        self.refresh_interval_seconds = self.settings.get('refresh_interval_minutes', 5) * 60
        self.next_refresh_seconds = self.refresh_interval_seconds
        self.next_refresh_timer = QTimer(self)
        self.next_refresh_timer.setInterval(1000)
        self.next_refresh_timer.timeout.connect(self._update_countdown)
        self.next_refresh_timer.start()

        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.timeout.connect(self._on_auto_refresh_timeout)
        self.auto_refresh_timer.start(self.refresh_interval_seconds * 1000)
        self._refresh_countdown_label()

    def _on_auto_refresh_timeout(self) -> None:
        self._reset_countdown()
        self.refresh_all()

    def _update_countdown(self) -> None:
        if self.next_refresh_seconds > 0:
            self.next_refresh_seconds -= 1
            self._refresh_countdown_label()

    def _reset_countdown(self) -> None:
        self.next_refresh_seconds = self.refresh_interval_seconds
        self._refresh_countdown_label()

    def _refresh_countdown_label(self) -> None:
        minutes = self.next_refresh_seconds // 60
        seconds = self.next_refresh_seconds % 60
        self.next_refresh_label.setText(f'Auto Refresh: {minutes:02d}:{seconds:02d}')

    def closeEvent(self, event) -> None:
        if not getattr(self, '_is_exiting', False) and self.tray_icon is not None and self.tray_icon.isVisible():
            self.hide()
            self.status_bar.showMessage('Minimized to system tray')
            event.ignore()
            return

        if hasattr(self, 'auto_refresh_timer') and self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.stop()
        if hasattr(self, 'next_refresh_timer') and self.next_refresh_timer.isActive():
            self.next_refresh_timer.stop()
        if self.active_worker is not None and self.active_worker.isRunning():
            self.active_worker.requestInterruption()
            finished = self.active_worker.wait(5000)
            if not finished:
                logging.warning('RefreshWorker did not stop within 5 seconds during shutdown.')
        if self.tray_icon is not None:
            self.tray_icon.hide()
        super().closeEvent(event)
