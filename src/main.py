#!/usr/bin/env python3
"""
道路設計アプリ エントリーポイント
"""
import sys
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("道路設計アプリ")
    app.setOrganizationName("RoadDesign")

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
