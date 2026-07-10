# Myntra Tracker Pro

Myntra Tracker Pro is a desktop product tracking application for Myntra. It monitors price and stock status changes in the background and notifies you when updates occur.

## Installation

1. Create and activate a Python 3.14 virtual environment (recommended):

   python -m venv venv
   venv\Scripts\activate

2. Install the dependencies:

   pip install -r requirements.txt

3. Install Playwright Chromium browser binaries:

   python -m playwright install chromium

4. Run the application:

   python app.py

## Features

- Modern PySide6 desktop GUI
- Add unlimited Myntra product URLs
- Background tracking with Playwright Chromium (headless)
- Tracks product name, brand, current price, original price, discount, stock status, and last checked time
- Auto refresh every 5 minutes without freezing the interface
- Detects price and stock changes and sends Windows notifications
- Save and load tracked products from `data/products.json`
- Delete products, refresh selected rows, refresh all, and export to CSV
- Logging to `logs/app.log`

## Build Executable

Run the build script to create a standalone Windows executable:

   build_exe.bat

The generated executable will be available in the `dist` folder.
