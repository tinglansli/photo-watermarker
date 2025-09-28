import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox
)

APP_NAME = "Photo Watermark 2"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 680)
        QApplication.setApplicationDisplayName(APP_NAME)

        self._build_menu()
        self.apply_fusion_dark()
        self.statusBar().showMessage("准备就绪")

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.about)
        help_menu.addAction(act_about)

    def about(self):
        QMessageBox.information(self, "关于", f"{APP_NAME}\n\nPySide6 最小示例。")

    def apply_fusion_dark(self):
        QApplication.setStyle("Fusion")
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(30, 30, 30))
        pal.setColor(QPalette.WindowText, Qt.white)
        pal.setColor(QPalette.Base, QColor(25, 25, 25))
        pal.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        pal.setColor(QPalette.ToolTipBase, Qt.white)
        pal.setColor(QPalette.ToolTipText, Qt.white)
        pal.setColor(QPalette.Text, Qt.white)
        pal.setColor(QPalette.Button, QColor(45, 45, 45))
        pal.setColor(QPalette.ButtonText, Qt.white)
        pal.setColor(QPalette.BrightText, Qt.red)
        pal.setColor(QPalette.Highlight, QColor(80, 130, 190))
        pal.setColor(QPalette.HighlightedText, Qt.white)
        self.setPalette(pal)

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
