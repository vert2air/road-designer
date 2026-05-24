#!/usr/bin/env python3
"""道路設計アプリ エントリーポイント。

起動方法
--------
    python src/main.py
    python src/main.py -i path/to/file.rdjson
    python src/main.py --input-file path/to/file.rdjson

依存ライブラリ
--------------
    PySide6 : UI フレームワーク（LGPL v3）
    Panda3D : 3D 走行ビューア（road_viewer.py が別プロセスで使用）
"""
import sys
import argparse
from PySide6.QtWidgets import QApplication
from main_window import MainWindow


def main() -> None:
    """アプリケーションを初期化して起動する。

    QApplication を生成し、MainWindow を表示してイベントループを開始する。
    ``-i``/``--input-file`` で起動時に読み込むファイルを指定できる。
    """
    parser = argparse.ArgumentParser(description="道路設計アプリ")
    parser.add_argument(
        "-i", "--input-file",
        metavar="FILE",
        help="起動時に読み込む rdjson ファイルのパス",
    )
    # QApplication が sys.argv を参照するため、Qt 用引数と分離する
    args, qt_args = parser.parse_known_args()

    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("道路設計アプリ")
    app.setOrganizationName("RoadDesign")

    win = MainWindow()
    win.show()

    if args.input_file:
        win._open_file(args.input_file)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
