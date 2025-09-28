# -*- coding: utf-8 -*-
"""
Photo Watermark 2 - 版本 #3：文本水印 + 拖拽定位（基础）
依赖: PySide6 (pip install PySide6)
"""

import sys, os
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QEvent, Signal, QPoint
from PySide6.QtGui import (
    QAction, QPalette, QColor, QPixmap, QImage, QPainter, QFont, QPen, QPainterPath
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QFileDialog, QHBoxLayout, QVBoxLayout, QLabel, QMessageBox, QSplitter,
    QAbstractItemView, QFrame, QFormLayout, QLineEdit, QFontComboBox, QSpinBox,
    QSlider, QPushButton, QColorDialog
)

APP_NAME = "Photo Watermark 2"
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

class ColorButton(QPushButton):
    colorChanged = Signal(QColor)
    def __init__(self, c=QColor("#FFFFFF"), text="选择颜色"):
        super().__init__(text)
        self._c = QColor(c)
        self.clicked.connect(self.pick)
        self._update_icon()
        self.setFixedHeight(28)
    def color(self): return self._c
    def setColor(self, c: QColor):
        self._c = QColor(c); self._update_icon(); self.colorChanged.emit(self._c)
    def _update_icon(self):
        pm = QPixmap(24,24); pm.fill(self._c)
        self.setIcon(pm); self.setIconSize(QSize(24,24))
    def pick(self):
        c = QColorDialog.getColor(self._c, self, "选择颜色")
        if c.isValid(): self.setColor(c)

class PreviewLabel(QLabel):
    positionChanged = Signal(float, float)  # pos_ratio
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setFrameShape(QFrame.StyledPanel)
        self.setAlignment(Qt.AlignCenter)
        self._base = QImage()
        self._scaled = QPixmap()
        self._offset = QPoint(0,0)
        self._scale = 1.0
        self._dragging = False
        self._last = QPoint()
        self.setMinimumSize(420, 320)

    def setImage(self, img: QImage):
        self._base = img
        self._update_scaled()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_scaled()

    def _update_scaled(self):
        if self._base.isNull():
            self._scaled = QPixmap(); return
        w,h = self._base.width(), self._base.height()
        if w==0 or h==0: self._scaled = QPixmap(); return
        scale = min(self.width()/w, self.height()/h); scale = max(scale, 1e-4)
        self._scale = scale
        sz = QSize(int(w*scale), int(h*scale))
        self._scaled = QPixmap.fromImage(self._base).scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._offset = QPoint((self.width()-sz.width())//2, (self.height()-sz.height())//2)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        if not self._scaled.isNull():
            p.drawPixmap(self._offset, self._scaled)
        # 画文本水印
        st = self.main.settings
        if not self._base.isNull() and st["text"].strip():
            wm = self.main.build_text_watermark()
            if not wm.isNull():
                x = int(st["pos_ratio_x"] * self._base.width()  * self._scale) + self._offset.x()
                y = int(st["pos_ratio_y"] * self._base.height() * self._scale) + self._offset.y()
                p.drawPixmap(x, y, wm.scaled(int(wm.width()*self._scale), int(wm.height()*self._scale),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self._base.isNull():
            self._dragging = True; self._last = e.pos(); e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging and not self._base.isNull():
            dx = (e.x()-self._last.x())/self._scale
            dy = (e.y()-self._last.y())/self._scale
            self._last = e.pos()
            st = self.main.settings
            W,H = self._base.width(), self._base.height()
            wm = self.main.build_text_watermark()
            ww, wh = (wm.width(), wm.height()) if not wm.isNull() else (0,0)
            x_px = st["pos_ratio_x"]*W + dx
            y_px = st["pos_ratio_y"]*H + dy
            x_px = clamp(x_px, 0, max(0, W-ww))
            y_px = clamp(y_px, 0, max(0, H-wh))
            self.positionChanged.emit(x_px/W if W>0 else 0, y_px/H if H>0 else 0)
            self.update(); e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button()==Qt.LeftButton and self._dragging:
            self._dragging=False; e.accept()
        else:
            super().mouseReleaseEvent(e)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 760)
        QApplication.setApplicationDisplayName(APP_NAME)

        # 初始设置（仅文本水印相关）
        self.settings = {
            "text": "@TingLans",
            "font_family": QFont().family(),
            "font_px": 72,
            "text_color": "#FFFFFF",
            "opacity": 80,  # 0~100
            "pos_ratio_x": 0.5,
            "pos_ratio_y": 0.5
        }

        self.images = []
        self._build_menu()
        self._build_ui()
        self.apply_fusion_dark()
        self.statusBar().showMessage("准备就绪")

    # ===== UI =====
    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        act_add = QAction("导入图片...", self); act_add.triggered.connect(self.action_import_files)
        act_add_dir = QAction("导入文件夹...", self); act_add_dir.triggered.connect(self.action_import_folder)
        act_clear = QAction("清空列表", self); act_clear.triggered.connect(self.action_clear_list)
        act_quit = QAction("退出", self); act_quit.triggered.connect(self.close)
        for a in (act_add, act_add_dir, act_clear, act_quit):
            file_menu.addAction(a)

        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于", self); act_about.triggered.connect(self.about)
        help_menu.addAction(act_about)

    def _build_ui(self):
        # 左：缩略图
        self.list = QListWidget(self)
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(112,84))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setSpacing(8)
        self.list.setMinimumWidth(200)
        self.list.itemSelectionChanged.connect(self.on_list_selection)

        # 中：预览
        self.preview = PreviewLabel(self)
        self.preview.positionChanged.connect(self.on_pos_changed)

        # 右：水印面板
        right = QWidget(); form = QFormLayout(right)
        self.edt_text = QLineEdit(self.settings["text"]); self.edt_text.textChanged.connect(self.on_settings_changed)
        self.font_combo = QFontComboBox(); self.font_combo.setCurrentFont(QFont(self.settings["font_family"]))
        self.font_combo.currentFontChanged.connect(self.on_settings_changed)
        self.spin_font = QSpinBox(); self.spin_font.setRange(8,300); self.spin_font.setValue(self.settings["font_px"])
        self.spin_font.valueChanged.connect(self.on_settings_changed)
        self.btn_color = ColorButton(QColor(self.settings["text_color"]), "选择字体颜色")
        self.btn_color.colorChanged.connect(self.on_settings_changed)
        self.slider_opacity = QSlider(Qt.Horizontal); self.slider_opacity.setRange(0,100)
        self.slider_opacity.setValue(self.settings["opacity"]); self.slider_opacity.valueChanged.connect(self.on_settings_changed)

        form.addRow("文本：", self.edt_text)
        form.addRow("字体：", self.font_combo)
        form.addRow("字号(px)：", self.spin_font)
        form.addRow("颜色：", self.btn_color)
        form.addRow("透明度：", self.slider_opacity)

        # 三栏
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list)
        splitter.addWidget(self.preview)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        self.setCentralWidget(splitter)

    # ===== 渲染 =====
    def build_text_watermark(self) -> QImage:
        text = self.settings["text"].strip()
        if not text: return QImage()
        font = QFont(self.settings["font_family"]); font.setPixelSize(int(self.settings["font_px"]))
        # 先测文本 bbox
        tmp = QImage(2,2, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(tmp); p.setFont(font)
        rect = p.fontMetrics().boundingRect(text)
        p.end()
        w = max(2, rect.width()+8); h = max(2, rect.height()+8)

        img = QImage(w,h, QImage.Format_ARGB32_Premultiplied); img.fill(Qt.transparent)
        p = QPainter(img); p.setRenderHints(QPainter.Antialiasing|QPainter.TextAntialiasing)
        p.setFont(font)
        path = QPainterPath(); baseline = p.fontMetrics().ascent() + 4
        path.addText(4, baseline, font, text)

        col = QColor(self.settings["text_color"])
        a = clamp(self.settings["opacity"]/100.0, 0.0, 1.0)
        fill = QColor(col.red(), col.green(), col.blue(), int(255*a))
        p.setPen(Qt.NoPen); p.setBrush(fill); p.drawPath(path)
        p.end()
        return img

    # ===== 事件 =====
    def on_pos_changed(self, xr, yr):
        self.settings["pos_ratio_x"] = float(xr)
        self.settings["pos_ratio_y"] = float(yr)
        self.preview.update()

    def on_settings_changed(self, *args):
        self.settings["text"] = self.edt_text.text()
        self.settings["font_family"] = self.font_combo.currentFont().family()
        self.settings["font_px"] = self.spin_font.value()
        self.settings["text_color"] = self.btn_color.color().name()
        self.settings["opacity"] = self.slider_opacity.value()
        self.preview.update()

    # ===== file ops =====
    def action_import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)"
        )
        if files: self.add_images(files)

    def action_import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not d: return
        paths=[]
        for name in os.listdir(d):
            p = Path(d)/name
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS: paths.append(str(p))
        if paths: self.add_images(paths)

    def action_clear_list(self):
        self.images.clear(); self.list.clear(); self.preview.setImage(QImage())
        self.statusBar().showMessage("已清空列表")

    def add_images(self, paths):
        added=0
        for p in paths:
            path=Path(p)
            if not path.exists() or path.suffix.lower() not in SUPPORTED_EXTS: continue
            if any(it["path"]==str(path) for it in self.images): continue
            img = QImage(str(path))
            if img.isNull(): continue
            self.images.append({"path":str(path), "img":img})
            icon = QPixmap.fromImage(img).scaled(112,84, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = QListWidgetItem(icon, path.name); item.setToolTip(str(path))
            self.list.addItem(item); added += 1
        if added>0 and self.list.currentRow()<0: self.list.setCurrentRow(0)
        self.statusBar().showMessage(f"已导入 {added} 张图片（总计 {len(self.images)}）")

    def on_list_selection(self):
        row = self.list.currentRow()
        if row<0 or row>=len(self.images): return
        self.preview.setImage(self.images[row]["img"])

    # ===== misc =====
    def about(self):
        QMessageBox.information(self, "关于", f"{APP_NAME}\n\n文本水印+拖拽定位版本。")

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
