# -*- coding: utf-8 -*-
"""
Photo Watermark 2 - 版本 #2：导入/缩略图/预览显示
依赖: PySide6 (pip install PySide6)
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QEvent, Signal, QPoint
from PySide6.QtGui import QAction, QPalette, QColor, QPixmap, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QFileDialog, QHBoxLayout, QVBoxLayout, QLabel, QMessageBox, QSplitter,
    QAbstractItemView, QFrame
)

APP_NAME = "Photo Watermark 2"
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

class PreviewLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setAlignment(Qt.AlignCenter)
        self._base_image = QImage()
        self._scaled_pixmap = QPixmap()
        self._offset = QPoint(0,0)
        self._scale = 1.0
        self.setMinimumSize(420, 320)

    def setImage(self, img: QImage):
        self._base_image = img
        self._update_scaled()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_scaled()

    def _update_scaled(self):
        if self._base_image.isNull():
            self._scaled_pixmap = QPixmap()
            return
        w, h = self._base_image.width(), self._base_image.height()
        if w == 0 or h == 0:
            self._scaled_pixmap = QPixmap()
            return
        scale = min(self.width()/w, self.height()/h)
        scale = max(scale, 1e-4)
        self._scale = scale
        sz = QSize(int(w*scale), int(h*scale))
        self._scaled_pixmap = QPixmap.fromImage(self._base_image).scaled(
            sz, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._offset = QPoint((self.width()-sz.width())//2, (self.height()-sz.height())//2)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        if not self._scaled_pixmap.isNull():
            p.drawPixmap(self._offset, self._scaled_pixmap)
        p.end()

class ThumbnailList(QListWidget):
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)

        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(112, 84))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSpacing(8)
        self.setMinimumWidth(200)

    def _has_supported(self, e) -> bool:
        md = e.mimeData()
        if not md.hasUrls(): return False
        for u in md.urls():
            p = Path(u.toLocalFile())
            if p.is_dir(): return True
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS: return True
        return False

    def _extract_paths(self, e):
        out = []
        md = e.mimeData()
        if not md.hasUrls(): return out
        for u in md.urls():
            p = Path(u.toLocalFile())
            if not p.exists(): continue
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                out.append(str(p))
            elif p.is_dir():
                for name in os.listdir(p):
                    f = p / name
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                        out.append(str(f))
        return out

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if self._has_supported(e) else e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if self._has_supported(e) else e.ignore()

    def dropEvent(self, e):
        paths = self._extract_paths(e)
        if paths:
            self.filesDropped.emit(paths)
            e.acceptProposedAction()
        else:
            e.ignore()

    def eventFilter(self, obj, e):
        if obj is self.viewport():
            if e.type() in (QEvent.DragEnter, QEvent.DragMove):
                if self._has_supported(e):
                    e.acceptProposedAction()
                    return True
            elif e.type() == QEvent.Drop:
                paths = self._extract_paths(e)
                if paths:
                    self.filesDropped.emit(paths)
                    e.acceptProposedAction()
                    return True
        return super().eventFilter(obj, e)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 760)
        QApplication.setApplicationDisplayName(APP_NAME)

        self.images = []  # [{"path":str, "img":QImage}]
        self._build_menu()
        self._build_ui()
        self.apply_fusion_dark()
        self.statusBar().showMessage("准备就绪")

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        act_add = QAction("导入图片...", self)
        act_add.triggered.connect(self.action_import_files)
        act_add_dir = QAction("导入文件夹...", self)
        act_add_dir.triggered.connect(self.action_import_folder)
        act_clear = QAction("清空列表", self)
        act_clear.triggered.connect(self.action_clear_list)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        for a in (act_add, act_add_dir, act_clear, act_quit):
            file_menu.addAction(a)

        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.about)
        help_menu.addAction(act_about)

    def _build_ui(self):
        self.list = ThumbnailList(self)
        self.list.itemSelectionChanged.connect(self.on_list_selection)
        self.list.filesDropped.connect(self.add_images)

        self.preview = PreviewLabel(self)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)

    # ===== file ops =====
    def action_import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)"
        )
        if files:
            self.add_images(files)

    def action_import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not d: return
        paths = []
        for name in os.listdir(d):
            p = Path(d) / name
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                paths.append(str(p))
        if paths:
            self.add_images(paths)

    def action_clear_list(self):
        self.images.clear()
        self.list.clear()
        self.preview.setImage(QImage())
        self.statusBar().showMessage("已清空列表")

    def add_images(self, paths):
        added = 0
        for p in paths:
            path = Path(p)
            if not path.exists() or path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            if any(it["path"] == str(path) for it in self.images):
                continue
            img = QImage(str(path))
            if img.isNull(): continue
            self.images.append({"path": str(path), "img": img})
            icon = QPixmap.fromImage(img).scaled(112,84, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = QListWidgetItem(icon, path.name)
            item.setToolTip(str(path))
            self.list.addItem(item)
            added += 1

        if added > 0 and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

        self.statusBar().showMessage(f"已导入 {added} 张图片（总计 {len(self.images)}）")

    def on_list_selection(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self.images):
            return
        self.preview.setImage(self.images[row]["img"])

    # ===== misc =====
    def about(self):
        QMessageBox.information(self, "关于", f"{APP_NAME}\n\n导入/预览版本。")

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
