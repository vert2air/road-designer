"""
tests/test_main.py

main.py の単体テスト。

main() 関数は QApplication 生成 → MainWindow 起動 → sys.exit(app.exec()) の
3ステップだけであり、sys.exit を呼ぶためイベントループに入ると戻らない。
そのため main() 自体の呼び出しはテストできない。

テスト可能な観点:
  - モジュールが正常にインポートできること（ImportError がないこと）
  - main 関数が定義されていること（callable であること）
  - __name__ == "__main__" の条件分岐が存在すること
  - モジュール docstring の記載内容が実態と一致すること
  - main() を直接呼ぶ代わりに、内部で生成されるオブジェクトの
    プロパティ（applicationName、organizationName）を検証すること

観点の分類:
  [仕様] 詳細設計書に記載された振る舞いの確認
  [エッジ] エッジケース・コーナーケース
"""
from __future__ import annotations
import sys
import os
import importlib
import inspect

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QApplication


def _main_source() -> str:
    """main.py のソースコードを返す（パスはモジュールの __file__ から取得）。"""
    import main
    with open(main.__file__, encoding='utf-8') as f:
        return f.read()

_app = QApplication.instance() or QApplication(sys.argv)


# ══════════════════════════════════════════════════════════════
# 1. インポート・定義の確認
# ══════════════════════════════════════════════════════════════

class TestImport:
    # [仕様] main モジュールが ImportError なしにインポートできる
    def test_importable(self):
        import main  # 例外にならない

    # [仕様] main 関数が定義されている
    def test_main_function_exists(self):
        import main
        assert hasattr(main, 'main')
        assert callable(main.main)

    # [仕様] main 関数の戻り値アノテーションが None
    def test_return_annotation_none(self):
        import main
        ann = inspect.get_annotations(main.main)
        assert ann.get('return') is None

    # [仕様] __name__ == "__main__" ガードが存在する
    def test_main_guard_exists(self):
        source = _main_source()
        assert 'if __name__ == "__main__"' in source
        assert 'main()' in source

    # [仕様] モジュール docstring が存在する
    def test_module_docstring_exists(self):
        import main
        assert main.__doc__ is not None
        assert len(main.__doc__) > 0

    # [仕様] 起動方法が docstring に記載されている
    def test_module_docstring_contains_usage(self):
        import main
        assert 'main.py' in main.__doc__

    # [仕様] main 関数の docstring が存在する
    def test_main_function_docstring(self):
        import main
        assert main.main.__doc__ is not None

    # [仕様] PyQt6.QtWidgets.QApplication をインポートしている
    def test_imports_qapplication(self):
        assert 'QApplication' in _main_source()

    # [仕様] main_window.MainWindow をインポートしている
    def test_imports_mainwindow(self):
        assert 'MainWindow' in _main_source()


# ══════════════════════════════════════════════════════════════
# 2. main() の内部動作（モックを使った検証）
# ══════════════════════════════════════════════════════════════

class TestMainFunction:
    # [仕様] main() は applicationName を "道路設計アプリ" に設定する
    def test_sets_application_name(self):
        import main
        captured = {}
        original_exit = sys.exit

        def fake_exit(code=0):
            raise SystemExit(code)

        class FakeApp:
            def __init__(self, argv):
                pass
            def setApplicationName(self, name):
                captured['appName'] = name
            def setOrganizationName(self, name):
                captured['orgName'] = name
            def exec(self):
                return 0

        class FakeWindow:
            def show(self):
                pass

        with patch('main.QApplication', FakeApp), \
             patch('main.MainWindow', FakeWindow), \
             patch('sys.exit', fake_exit):
            try:
                main.main()
            except SystemExit:
                pass

        assert captured.get('appName') == '道路設計アプリ'

    # [仕様] main() は organizationName を "RoadDesign" に設定する
    def test_sets_organization_name(self):
        import main
        captured = {}

        class FakeApp:
            def __init__(self, argv):
                pass
            def setApplicationName(self, name):
                pass
            def setOrganizationName(self, name):
                captured['orgName'] = name
            def exec(self):
                return 0

        class FakeWindow:
            def show(self):
                pass

        with patch('main.QApplication', FakeApp), \
             patch('main.MainWindow', FakeWindow), \
             patch('sys.exit', lambda c=0: (_ for _ in ()).throw(SystemExit(c))):
            try:
                main.main()
            except SystemExit:
                pass

        assert captured.get('orgName') == 'RoadDesign'

    # [仕様] main() は MainWindow を生成して show() を呼ぶ
    def test_creates_and_shows_mainwindow(self):
        import main
        shown = []

        class FakeApp:
            def __init__(self, argv): pass
            def setApplicationName(self, n): pass
            def setOrganizationName(self, n): pass
            def exec(self): return 0

        class FakeWindow:
            def show(self):
                shown.append(True)

        with patch('main.QApplication', FakeApp), \
             patch('main.MainWindow', FakeWindow), \
             patch('sys.exit', lambda c=0: (_ for _ in ()).throw(SystemExit(c))):
            try:
                main.main()
            except SystemExit:
                pass

        assert shown == [True]

    # [仕様] main() は app.exec() の戻り値を sys.exit に渡す
    def test_passes_exec_result_to_sys_exit(self):
        import main
        exit_codes = []

        class FakeApp:
            def __init__(self, argv): pass
            def setApplicationName(self, n): pass
            def setOrganizationName(self, n): pass
            def exec(self): return 42  # 終了コード 42

        class FakeWindow:
            def show(self): pass

        def fake_exit(code=0):
            exit_codes.append(code)
            raise SystemExit(code)

        with patch('main.QApplication', FakeApp), \
             patch('main.MainWindow', FakeWindow), \
             patch('sys.exit', fake_exit):
            try:
                main.main()
            except SystemExit:
                pass

        assert exit_codes == [42]

    # [エッジ] MainWindow のコンストラクタが例外を投げても
    # main() の外に伝播する（sys.exit でラップしない）
    def test_mainwindow_exception_propagates(self):
        import main

        class FakeApp:
            def __init__(self, argv): pass
            def setApplicationName(self, n): pass
            def setOrganizationName(self, n): pass
            def exec(self): return 0

        class BrokenWindow:
            def __init__(self):
                raise RuntimeError("window init failed")

        with patch('main.QApplication', FakeApp), \
             patch('main.MainWindow', BrokenWindow):
            with pytest.raises(RuntimeError, match="window init failed"):
                main.main()
