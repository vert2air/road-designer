#!/usr/bin/env python3
"""道路設計アプリ エントリーポイント。

起動方法
--------
    python src/main.py

依存ライブラリ
--------------
    PySide6 : UI フレームワーク（LGPL v3）
    Panda3D : 3D 走行ビューア（road_viewer.py が別プロセスで使用）
"""
import sys
from PySide6.QtWidgets import QApplication
from main_window import MainWindow


def main() -> None:
    """アプリケーションを初期化して起動する。

    QApplication を生成し、MainWindow を表示してイベントループを開始する。
    イベントループ終了時に sys.exit へ渡すことで終了コードを呼び出し元に伝播させる。
    """
    app = QApplication(sys.argv)
    app.setApplicationName("道路設計アプリ")
    app.setOrganizationName("RoadDesign")

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
