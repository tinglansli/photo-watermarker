# -*- coding: utf-8 -*-
"""
Photo Watermark 2 - 单文件桌面应用 (Windows / macOS)
依赖: PySide6 (pip install PySide6)
作者: ChatGPT
"""

import os
import sys
import json
import math
from pathlib import Path
import platform, subprocess

from PySide6.QtCore import (
    Qt, QSize, QRect, QPoint, QPointF, QStandardPaths, QByteArray, QEvent, Signal, QObject
)
from PySide6.QtGui import (
    QAction, QIcon, QPixmap, QImage, QPainter, QColor, QFont, QFontDatabase,
    QPen, QPainterPath, QTransform, QGuiApplication, QPalette
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QListWidget, QListWidgetItem,
    QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSplitter, QGroupBox, QFormLayout,
    QLineEdit, QFontComboBox, QSpinBox, QCheckBox, QColorDialog, QSlider, QComboBox,
    QMessageBox, QToolButton, QGridLayout, QProgressBar, QTabWidget, QFrame, QStyle,
    QAbstractItemView, QProgressDialog, QScrollArea, QSizePolicy, QInputDialog
)

APP_NAME = "Photo Watermark 2"
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

def human_path(p: Path) -> str:
    try:
        return str(p)
    except Exception:
        return p.as_posix()

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def project_root() -> Path:
    # Windows：打包(onefile)后放在 exe 同级目录；源码运行用项目根
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    else:
        return Path(__file__).resolve().parents[2]

def app_data_dir() -> Path:
    p = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    p.mkdir(parents=True, exist_ok=True)
    (p / "templates").mkdir(parents=True, exist_ok=True)
    return p

def templates_dir() -> Path:
    p = project_root() / "templates"
    p.mkdir(parents=True, exist_ok=True)
    return p

def default_template_path() -> Path:
    return templates_dir() / "default.json"

def last_session_path() -> Path:
    return templates_dir() / "last_session.json"

def default_settings() -> dict:
    return {
        "watermark_type": "text",  # text | image
        "text": "@TingLans",
        "font_family": QFont().family(),
        "font_px": 128,
        "bold": False,
        "italic": False,
        "text_color": "#FFFFFF",
        "opacity": 70,  # 0~100
        "outline": True,
        "outline_px": 2,
        "outline_color": "#000000",
        "shadow": True,
        "shadow_dx": 2,
        "shadow_dy": 2,
        "shadow_color": "rgba(0,0,0,128)",

        "image_path": "",
        "image_scale_percent": 40,   # 10~300
        "image_opacity": 70,         # 0~100

        "rotation_deg": 0,  # -180 ~ 180

        # 位置：两种模式
        # anchor: tl,tc,tr,cl,cc,cr,bl,bc,br,custom
        "anchor": "br",
        # custom 拖拽时使用的相对坐标 (以原图尺寸为基准的左上角比例)
        "pos_ratio_x": 0.75,
        "pos_ratio_y": 0.75,

        "export": {
            "output_dir": "",
            "prevent_export_to_source": True,

            "out_format": "PNG",      # PNG | JPEG
            "jpeg_quality": 90,       # 0~100

            "resize_mode": "none",    # none|width|height|percent
            "resize_value": 100,

            "name_rule": "suffix",    # keep|prefix|suffix
            "name_value": "_watermarked"
        }
    }


# ------------------ 颜色按钮 ------------------
class ColorButton(QPushButton):
    colorChanged = Signal(QColor)

    def __init__(self, color=QColor("#FFFFFF"), text="选择颜色"):
        super().__init__(text)
        self._color = QColor(color)
        self.clicked.connect(self.pick)
        self.setFixedHeight(28)
        self.update_style()

    def color(self) -> QColor:
        return self._color

    def setColor(self, c: QColor):
        self._color = QColor(c)
        self.update_style()
        self.colorChanged.emit(self._color)

    def update_style(self):
        # 在按钮左侧绘制一个色块
        self.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding-left: 36px;
                height: 28px;
            }}
            QPushButton::before {{
            }}
        """)
        # 使用 icon 显示色块
        pm = QPixmap(24, 24)
        pm.fill(self._color)
        self.setIcon(QIcon(pm))
        self.setIconSize(QSize(24, 24))

    def pick(self):
        c = QColorDialog.getColor(self._color, self, "选择颜色")
        if c.isValid():
            self.setColor(c)


# ------------------ 预览控件（可拖拽水印） ------------------
class PreviewLabel(QLabel):
    # 需要主窗口提供生成“用于预览”的水印 QPixmap 以及返回原图尺寸、当前 anchor 等
    requestPreviewWatermark = Signal()
    positionChanged = Signal(float, float)  # pos_ratio_x, pos_ratio_y

    def __init__(self, main):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.main = main

        self._base_image = QImage()
        self._base_path = ""
        self._scaled_pixmap = QPixmap()
        self._scale_factor = 1.0  # 预览图相对原图的缩放（宽度比）
        self._offset = QPoint(0, 0)  # 预览区域中图像相对于label的偏移（居中留黑边时）
        self._dragging = False
        self._last_mouse = QPoint()
        self._wm_prev_pix = QPixmap()
        self._wm_prev_size = QSize()

        self.setMinimumSize(420, 360)

    def setImage(self, img: QImage, path: str):
        self._base_image = img
        self._base_path = path
        self.updateScaledPixmap()
        self.update()

    def sizeHint(self):
        return QSize(800, 520)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.updateScaledPixmap()

    def updateScaledPixmap(self):
        if self._base_image.isNull():
            self._scaled_pixmap = QPixmap()
            self._scale_factor = 1.0
            self._offset = QPoint(0, 0)
            return
        avail = self.size()
        img_w = self._base_image.width()
        img_h = self._base_image.height()
        if img_w == 0 or img_h == 0:
            return
        scale = min(avail.width() / img_w, avail.height() / img_h)
        scale = max(scale, 0.0001)
        self._scale_factor = scale
        scaled_size = QSize(int(img_w * scale), int(img_h * scale))
        pm = QPixmap.fromImage(self._base_image).scaled(
            scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._scaled_pixmap = pm
        self._offset = QPoint(
            (avail.width() - scaled_size.width()) // 2,
            (avail.height() - scaled_size.height()) // 2
        )
        # 预先请求一次水印（用于命中测试）
        self.requestPreviewWatermark.emit()

    def paintEvent(self, e):
        super().paintEvent(e)

        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)

        # 1) 无图：居中画“预览”，并结束
        if self._base_image.isNull():
            hint = "预览"
            p.setPen(QColor(200, 200, 200, 180))
            f = p.font(); f.setPointSize(14); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, hint)
            p.end()
            return

        # 2) 画底图
        if not self._scaled_pixmap.isNull():
            p.drawPixmap(self._offset, self._scaled_pixmap)

        # 3) 画水印（不在 paintEvent 里发信号/做计算，只使用缓存的 _wm_prev_pix）
        wm = self._wm_prev_pix
        if not wm.isNull():
            st = self.main.settings
            base_w = self._base_image.width()
            base_h = self._base_image.height()
            anchor = st.get("anchor", "custom")

            if anchor != "custom":
                x_px, y_px = self.main.calc_anchor_top_left(
                    anchor, base_w, base_h,
                    for_preview=True, wm_preview_size=wm.size()
                )
                x_ratio = x_px / base_w
                y_ratio = y_px / base_h
            else:
                x_ratio = float(st.get("pos_ratio_x", 0.5))
                y_ratio = float(st.get("pos_ratio_y", 0.5))

            x = self._offset.x() + int(x_ratio * base_w * self._scale_factor)
            y = self._offset.y() + int(y_ratio * base_h * self._scale_factor)
            p.drawPixmap(x, y, wm)

        p.end()


    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self._base_image.isNull():
            # 若点中水印范围，开始拖拽；否则也允许从任意处拖拽
            self._dragging = True
            self._last_mouse = e.pos()
            # —— 兜底：若当前是预设锚点（非 custom），先把当前位置折算为 pos_ratio 再切到 custom
            if self.main.settings.get("anchor", "custom") != "custom":
                base_w, base_h = self._base_image.width(), self._base_image.height()
                # 确保有最新的预览水印尺寸（若为空则先请求一次）
                if self._wm_prev_pix.isNull():
                    self.requestPreviewWatermark.emit()

                # 利用预览尺寸换算到原图坐标，得到当前显示的左上角像素位置
                x_px, y_px = self.main.calc_anchor_top_left(
                    self.main.settings.get("anchor", "cc"),
                    base_w, base_h,
                    for_preview=True,
                    wm_preview_size=self._wm_prev_pix.size()
                )
                if base_w > 0 and base_h > 0:
                    self.main.settings["pos_ratio_x"] = x_px / base_w
                    self.main.settings["pos_ratio_y"] = y_px / base_h

                # 再切换为 custom
                self.main.settings["anchor"] = "custom"

            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging and not self._base_image.isNull():
            delta = e.pos() - self._last_mouse
            self._last_mouse = e.pos()

            # 当前 pos 比例，换算为像素（以原图）
            st = self.main.settings
            base_w = self._base_image.width()
            base_h = self._base_image.height()
            wm = self._wm_prev_pix
            wm_w = wm.width() / self._scale_factor  # 转回原图像素
            wm_h = wm.height() / self._scale_factor

            x_ratio = float(st.get("pos_ratio_x", 0.5))
            y_ratio = float(st.get("pos_ratio_y", 0.5))

            dx_img = delta.x() / self._scale_factor
            dy_img = delta.y() / self._scale_factor

            x_px = x_ratio * base_w + dx_img
            y_px = y_ratio * base_h + dy_img

            # 限制不超出图像边界
            x_px = clamp(x_px, 0, max(0, base_w - wm_w))
            y_px = clamp(y_px, 0, max(0, base_h - wm_h))

            x_ratio = x_px / base_w if base_w > 0 else 0
            y_ratio = y_px / base_h if base_h > 0 else 0

            self.positionChanged.emit(x_ratio, y_ratio)
            self.update()
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    # 外部回调，将预览用水印像素图传进来，减少重复计算
    def setPreviewWatermarkPixmap(self, pm: QPixmap):
        self._wm_prev_pix = pm if isinstance(pm, QPixmap) else QPixmap()
        self._wm_prev_size = self._wm_prev_pix.size()

# ===== 可拖拽缩略图列表（空态提示 + 文件/文件夹拖入，兼容 viewport 事件） =====
class ThumbnailList(QListWidget):
    filesDropped = Signal(list)  # 发射文件路径列表（str）

    def __init__(self, parent=None):
        super().__init__(parent)
        # 列表本体 & 视口都接收拖拽
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.viewport().setAcceptDrops(True)
        # 把 viewport 的拖拽相关事件也拦下来
        self.viewport().installEventFilter(self)

        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSpacing(8)

    # --- 直接落在 QListWidget 上的拖拽 ---
    def dragEnterEvent(self, e):
        if self._has_supported_urls(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._has_supported_urls(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        paths = self._extract_paths(e)
        if paths:
            self.filesDropped.emit(paths)
            e.acceptProposedAction()
        else:
            e.ignore()

    # --- 兼容：落在 viewport() 上的拖拽，通过事件过滤器处理 ---
    def eventFilter(self, obj, e):
        if obj is self.viewport():
            if e.type() in (QEvent.DragEnter, QEvent.DragMove):
                if self._has_supported_urls(e):
                    e.acceptProposedAction()
                    return True
            elif e.type() == QEvent.Drop:
                paths = self._extract_paths(e)
                if paths:
                    self.filesDropped.emit(paths)
                    e.acceptProposedAction()
                    return True
        return super().eventFilter(obj, e)

    # --- 工具：校验 & 提取路径 ---
    def _has_supported_urls(self, e) -> bool:
        md = e.mimeData()
        if not md.hasUrls():
            return False
        for u in md.urls():
            p = Path(u.toLocalFile())
            if p.is_dir():
                return True
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                return True
        return False

    def _extract_paths(self, e) -> list:
        md = e.mimeData()
        if not md.hasUrls():
            return []
        paths = []
        for u in md.urls():
            p = Path(u.toLocalFile())
            if not p.exists():
                continue
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                paths.append(str(p))
            elif p.is_dir():
                # 仅扫描一层
                for name in os.listdir(p):
                    f = p / name
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                        paths.append(str(f))
        return paths

    # 空态提示：列表为空时居中画字
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            p = QPainter(self.viewport())
            p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            rect = self.viewport().rect()
            hint = "拖入或导入图片文件"
            p.setPen(QColor(180, 180, 180, 180))
            font = p.font(); font.setPointSize(12); p.setFont(font)
            p.drawText(rect, Qt.AlignCenter, hint)
            p.end()

# ------------------ 主窗口 ------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1260, 760)
        QApplication.setApplicationDisplayName(APP_NAME)

        # 状态
        self.settings = default_settings()
        self.images = []  # [{"path":str, "img":QImage, "w":int, "h":int}]
        self.current_index = -1
        self._wm_cache_for_export = {}  # (base_size_tuple)->QImage 缓存

        # UI
        self._build_ui()
        self.apply_fusion_theme()
        self.load_last_session()

        self.setAcceptDrops(True)
        
        # 禁用所有控件的鼠标滚轮操作
        self.setWheelEventForControls()

    # ---------- UI ----------
    def _wrap_scroll(self, w: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(w)
        sa.setStyleSheet("QScrollArea { background: transparent; }")
        return sa
    
    def _build_ui(self):
        # 顶部菜单
        self._build_menu()

        # ===== 左侧：缩略图列表 =====
        self.list = ThumbnailList(self)
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(112, 84))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemSelectionChanged.connect(self.on_list_selection)
        self.list.setSpacing(8)
        self.list.setStyleSheet(
            "QListWidget{background:#1f1f1f; color:#ddd;} "
            "QListWidget::item{ border:1px solid #333; } "
            "QListWidget::item:selected{ border:2px solid #4da3ff; background:#333; }"
        )
        self.list.setMinimumWidth(180)   # 更窄一些即可看清缩略图和文件名
        self.list.setMaximumWidth(520)   # 防止被拖得过宽

        # 关键：接收拖入文件/文件夹并复用你现有的批量导入逻辑
        self.list.filesDropped.connect(self.add_images)

        # 包装成左侧容器
        self.left_widget = QWidget()
        left_layout = QVBoxLayout(self.left_widget)
        left_layout.setContentsMargins(0,0,0,0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.list)

        # ===== 中间：预览 =====
        self.preview = PreviewLabel(self)
        self.preview.requestPreviewWatermark.connect(self.update_preview_watermark)
        self.preview.positionChanged.connect(self.on_preview_pos_changed)
        self.preview.setMinimumSize(400, 300)

        self.middle_widget = QWidget()
        middle_layout = QVBoxLayout(self.middle_widget)
        middle_layout.setContentsMargins(6,6,6,6)
        middle_layout.setSpacing(6)
        middle_layout.addWidget(self.preview)

        # ===== 右侧：控制面板（Tab + Scroll）=====
        tab_watermark = self.build_watermark_tab()
        tab_export = self.build_export_tab()
        tab_templates = self.build_template_tab()

        tabs = QTabWidget()
        tabs.addTab(self._wrap_scroll(tab_watermark), "水印")
        tabs.addTab(self._wrap_scroll(tab_export), "导出")
        tabs.addTab(self._wrap_scroll(tab_templates), "模板")
        tabs.setMinimumWidth(320)

        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)
        right_layout.setContentsMargins(6,6,6,6)
        right_layout.setSpacing(6)
        right_layout.addWidget(tabs)

        # ===== 三栏可拖动分隔 =====
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(6)

        self.main_splitter.addWidget(self.left_widget)
        self.main_splitter.addWidget(self.middle_widget)
        self.main_splitter.addWidget(self.right_widget)

        # 伸缩因子：左(1) 中(3) 右(3) —— 预览与参数更宽
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setStretchFactor(2, 3)

        # 初始尺寸（可按屏幕自行调整）
        self.main_splitter.setSizes([260, 760, 620])

        # 最小宽度保护，避免被拖没
        self.left_widget.setMinimumWidth(140)
        self.right_widget.setMinimumWidth(340)

        # 直接把分割器设为中央部件（避免再包一层 QWidget+Layout）
        self.setCentralWidget(self.main_splitter)

        # 底部状态栏
        self.statusBar().showMessage("准备就绪")


    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")

        act_add = QAction("导入图片...", self)
        act_add.triggered.connect(self.action_import_files)
        act_add_folder = QAction("导入文件夹...", self)
        act_add_folder.triggered.connect(self.action_import_folder)
        act_clear = QAction("清空列表", self)
        act_clear.triggered.connect(self.action_clear_list)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)

        file_menu.addAction(act_add)
        file_menu.addAction(act_add_folder)
        file_menu.addSeparator()
        file_menu.addAction(act_clear)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        exp_menu = menubar.addMenu("导出")
        act_export_one = QAction("导出当前", self)
        act_export_one.triggered.connect(self.export_current)
        act_export_all = QAction("批量导出全部", self)
        act_export_all.triggered.connect(self.export_all)
        exp_menu.addAction(act_export_one)
        exp_menu.addAction(act_export_all)

        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.about)
        help_menu.addAction(act_about)

    # ---------- Tabs ----------  
    def build_watermark_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 水印类型
        type_box = QGroupBox("水印类型")
        f = QFormLayout(type_box)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["文本水印", "图片水印"])
        self.combo_type.currentIndexChanged.connect(self.on_type_changed)
        f.addRow("类型：", self.combo_type)
        layout.addWidget(type_box)

        # 文本水印
        self.gb_text = QGroupBox("文本水印")
        tf = QFormLayout(self.gb_text)
        tf.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        tf.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.edt_text = QLineEdit(self.settings["text"])
        self.edt_text.textChanged.connect(self.on_settings_changed)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self.settings["font_family"]))
        self.font_combo.currentFontChanged.connect(self.on_settings_changed)
        self.spin_font = QSpinBox()
        self.spin_font.setRange(6, 300)
        self.spin_font.setValue(self.settings["font_px"])
        self.spin_font.valueChanged.connect(self.on_settings_changed)
        self.chk_bold = QCheckBox("粗体")
        self.chk_bold.setChecked(self.settings["bold"])
        self.chk_bold.stateChanged.connect(self.on_settings_changed)
        self.chk_italic = QCheckBox("斜体")
        self.chk_italic.setChecked(self.settings["italic"])
        self.chk_italic.stateChanged.connect(self.on_settings_changed)
        self.btn_text_color = ColorButton(QColor(self.settings["text_color"]), "选择字体颜色")
        self.btn_text_color.colorChanged.connect(self.on_settings_changed)
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(self.settings["opacity"])
        self.slider_opacity.valueChanged.connect(self.on_settings_changed)

        # 描边与阴影
        self.chk_outline = QCheckBox("描边")
        self.chk_outline.setChecked(self.settings["outline"])
        self.chk_outline.stateChanged.connect(self.on_settings_changed)
        self.spin_outline = QSpinBox()
        self.spin_outline.setRange(1, 20)
        self.spin_outline.setValue(self.settings["outline_px"])
        self.spin_outline.valueChanged.connect(self.on_settings_changed)
        self.btn_outline_color = ColorButton(QColor(self.settings["outline_color"]), "描边颜色")
        self.btn_outline_color.colorChanged.connect(self.on_settings_changed)

        self.chk_shadow = QCheckBox("阴影")
        self.chk_shadow.setChecked(self.settings["shadow"])
        self.chk_shadow.stateChanged.connect(self.on_settings_changed)
        self.spin_shadow_dx = QSpinBox(); self.spin_shadow_dx.setRange(-50, 50); self.spin_shadow_dx.setValue(self.settings["shadow_dx"])
        self.spin_shadow_dy = QSpinBox(); self.spin_shadow_dy.setRange(-50, 50); self.spin_shadow_dy.setValue(self.settings["shadow_dy"])
        self.spin_shadow_dx.valueChanged.connect(self.on_settings_changed)
        self.spin_shadow_dy.valueChanged.connect(self.on_settings_changed)
        self.btn_shadow_color = ColorButton(QColor(0,0,0,128), "阴影颜色")
        self.btn_shadow_color.colorChanged.connect(self.on_settings_changed)

        tf.addRow("文本：", self.edt_text)
        tf.addRow("字体：", self.font_combo)
        tf.addRow("字号(px)：", self.spin_font)
        tf.addRow("样式：", self._hbox([self.chk_bold, self.chk_italic]))
        tf.addRow("颜色：", self.btn_text_color)
        tf.addRow("透明度：", self.slider_opacity)
        tf.addRow("描边：", self._hbox([self.chk_outline, QLabel("宽(px)"), self.spin_outline, self.btn_outline_color]))
        tf.addRow("阴影：", self._hbox([self.chk_shadow, QLabel("dx"), self.spin_shadow_dx, QLabel("dy"), self.spin_shadow_dy, self.btn_shadow_color]))
        layout.addWidget(self.gb_text)

        # 图片水印
        self.gb_image = QGroupBox("图片水印")
        gf = QFormLayout(self.gb_image)
        gf.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        gf.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.lbl_wm_img = QLabel("未选择")
        self.btn_pick_wm_img = QPushButton("选择图片")
        self.btn_pick_wm_img.clicked.connect(self.pick_watermark_image)
        self.slider_img_scale = QSlider(Qt.Horizontal); self.slider_img_scale.setRange(10, 300); self.slider_img_scale.setValue(self.settings["image_scale_percent"]); self.slider_img_scale.valueChanged.connect(self.on_settings_changed)
        self.slider_img_opacity = QSlider(Qt.Horizontal); self.slider_img_opacity.setRange(0,100); self.slider_img_opacity.setValue(self.settings["image_opacity"]); self.slider_img_opacity.valueChanged.connect(self.on_settings_changed)

        gf.addRow("水印图片：", self._hbox([self.btn_pick_wm_img, self.lbl_wm_img]))
        gf.addRow("缩放(%)：", self.slider_img_scale)
        gf.addRow("透明度：", self.slider_img_opacity)
        layout.addWidget(self.gb_image)

        # 布局与旋转
        pos_box = QGroupBox("布局与旋转")
        v = QVBoxLayout(pos_box)
        grid = QGridLayout()
        self.grid_btns = {}
        tags = [
            ("tl","↖"), ("tc","↑"), ("tr","↗"),
            ("cl","←"), ("cc","●"), ("cr","→"),
            ("bl","↙"), ("bc","↓"), ("br","↘")
        ]
        for i,(key,text) in enumerate(tags):
            b = QToolButton(); b.setText(text); b.setToolTip(key); b.setFixedSize(36, 28)
            b.clicked.connect(lambda _,k=key: self.on_anchor_clicked(k))
            grid.addWidget(b, i//3, i%3)
            self.grid_btns[key] = b
        v.addLayout(grid)

        rot_line = QHBoxLayout()
        self.slider_rot = QSlider(Qt.Horizontal); self.slider_rot.setRange(-180, 180); self.slider_rot.setValue(self.settings["rotation_deg"]); self.slider_rot.valueChanged.connect(self.on_settings_changed)
        self.lbl_rot = QLabel(f"{self.settings['rotation_deg']}°")
        self.slider_rot.valueChanged.connect(lambda v: self.lbl_rot.setText(f"{v}°"))
        rot_line.addWidget(QLabel("旋转："))
        rot_line.addWidget(self.slider_rot)
        rot_line.addWidget(self.lbl_rot)
        v.addLayout(rot_line)

        btn_reset = QPushButton("重置位置为中心")
        btn_reset.clicked.connect(lambda: self.on_anchor_clicked("cc"))
        v.addWidget(btn_reset)

        layout.addWidget(pos_box)
        layout.addStretch(1)

        # 初始显示
        self.on_type_changed()
        return w

    def build_export_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(10)

        # 输出设置
        gb = QGroupBox("输出设置")
        f = QFormLayout(gb)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        f.setRowWrapPolicy(QFormLayout.DontWrapRows)

        self.edt_outdir = QLineEdit(self.settings["export"]["output_dir"])
        self.edt_outdir.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        btn_outdir = QPushButton("选择...")
        btn_outdir.setFixedWidth(88)
        btn_outdir.clicked.connect(self.pick_outdir)

        row_outdir = QWidget()
        hl = QHBoxLayout(row_outdir)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self.edt_outdir, 1)   # 伸展占满
        hl.addWidget(btn_outdir, 0)        # 右侧贴边按钮
        f.addRow("输出文件夹：", row_outdir)

        self.chk_prevent = QCheckBox("阻止导出到原文件夹（如果需要导出到原文件夹，请取消勾选）")
        self.chk_prevent.setChecked(self.settings["export"]["prevent_export_to_source"])
        self.chk_prevent.stateChanged.connect(self.on_settings_changed)
        f.addRow("", self.chk_prevent)

        self.combo_format = QComboBox()
        self.combo_format.addItems(["PNG", "JPEG"])
        self.combo_format.setCurrentText(self.settings["export"]["out_format"])
        self.combo_format.currentTextChanged.connect(self.on_settings_changed)
        self.slider_quality = QSlider(Qt.Horizontal); self.slider_quality.setRange(0,100); self.slider_quality.setValue(self.settings["export"]["jpeg_quality"])
        self.slider_quality.valueChanged.connect(self.on_settings_changed)
        self.lbl_quality = QLabel(f"{self.settings['export']['jpeg_quality']}")
        self.slider_quality.valueChanged.connect(lambda v: self.lbl_quality.setText(str(v)))
        f.addRow("输出格式：", self.combo_format)
        f.addRow("JPEG质量：", self._hbox([self.slider_quality, self.lbl_quality]))

        # 尺寸调整
        self.combo_resize = QComboBox()
        self.combo_resize.addItems(["不缩放", "按宽度", "按高度", "按百分比"])
        mode_map = {"none": "不缩放", "width":"按宽度", "height":"按高度", "percent":"按百分比"}
        self.combo_resize.setCurrentText(mode_map.get(self.settings["export"]["resize_mode"], "不缩放"))
        self.combo_resize.currentIndexChanged.connect(self.on_settings_changed)
        self.spin_resize = QSpinBox(); self.spin_resize.setRange(1, 10000); self.spin_resize.setValue(self.settings["export"]["resize_value"])
        self.spin_resize.valueChanged.connect(self.on_settings_changed)
        f.addRow("尺寸调整：", self._hbox([self.combo_resize, self.spin_resize]))

        # 命名规则
        self.combo_name_rule = QComboBox()
        self.combo_name_rule.addItems(["保留原文件名", "添加前缀", "添加后缀"])
        rule_map = {"keep":"保留原文件名","prefix":"添加前缀","suffix":"添加后缀"}
        self.combo_name_rule.setCurrentText(rule_map.get(self.settings["export"]["name_rule"], "添加后缀"))
        self.combo_name_rule.currentIndexChanged.connect(self.on_settings_changed)
        self.edt_name_value = QLineEdit(self.settings["export"]["name_value"])
        self.edt_name_value.textChanged.connect(self.on_settings_changed)
        f.addRow("命名规则：", self.combo_name_rule)
        f.addRow("前/后缀：", self.edt_name_value)

        layout.addWidget(gb)

        # 导出操作
        btns = QHBoxLayout()
        self.btn_export_current = QPushButton("导出当前")
        self.btn_export_current.clicked.connect(self.export_current)
        self.btn_export_all = QPushButton("批量导出全部")
        self.btn_export_all.clicked.connect(self.export_all)
        btns.addWidget(self.btn_export_current)
        btns.addWidget(self.btn_export_all)
        layout.addLayout(btns)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        layout.addStretch(1)
        self.update_jpeg_controls()
        return w

    def build_template_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 顶部：打开模板文件夹
        row_top = QHBoxLayout()
        b_open_folder = QPushButton("打开模板文件夹")
        b_open_folder.setMinimumHeight(36)
        b_open_folder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_top.addWidget(b_open_folder)
        layout.addLayout(row_top)

        # 中部：模板列表（更大、更美观）
        self.template_list = QListWidget()
        self.template_list.setSpacing(8)
        self.template_list.setAlternatingRowColors(False)
        self.template_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.template_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.template_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.template_list.setStyleSheet("""
            QListWidget {
                background: #202020;
                border: 1px solid #333;
                padding: 6px;
            }
            QListWidget::item {
                background: #2a2a2a;
                color: #e8e8e8;
                border: 1px solid #3a3a3a;
                border-radius: 10px;
                padding: 10px 14px;
                margin: 0px;  /* 间距由 setSpacing 控制 */
            }
            QListWidget::item:hover {
                background: #333333;
                border-color: #4a90e2;
            }
            QListWidget::item:selected {
                background: #3b4f6b;
                border: 1px solid #4a90e2;
                color: #ffffff;
            }
        """)
        self.refresh_template_list()
        layout.addWidget(self.template_list, stretch=1)

        # 底部第 1 行：加载所选 / 设为默认 —— 两个按钮均占半行宽
        grid1 = QGridLayout()
        grid1.setContentsMargins(0, 0, 0, 0)
        grid1.setHorizontalSpacing(8)
        b_load_selected = QPushButton("加载所选模板")
        b_set_default  = QPushButton("设为默认模板")
        for b in (b_load_selected, b_set_default):
            b.setMinimumHeight(36)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid1.addWidget(b_load_selected, 0, 0)
        grid1.addWidget(b_set_default,  0, 1)
        grid1.setColumnStretch(0, 1)
        grid1.setColumnStretch(1, 1)
        layout.addLayout(grid1)

        # 底部第 2 行：保存新模板 / 删除所选 —— 两个按钮均占半行宽
        grid2 = QGridLayout()
        grid2.setContentsMargins(0, 0, 0, 0)
        grid2.setHorizontalSpacing(8)
        b_save_new = QPushButton("保存为新模板")
        b_delete   = QPushButton("删除所选模板")
        for b in (b_save_new, b_delete):
            b.setMinimumHeight(36)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid2.addWidget(b_save_new, 0, 0)
        grid2.addWidget(b_delete,   0, 1)
        grid2.setColumnStretch(0, 1)
        grid2.setColumnStretch(1, 1)
        layout.addLayout(grid2)

        # 信号连接
        b_open_folder.clicked.connect(self.template_open_folder)
        b_load_selected.clicked.connect(self.template_load_selected)
        b_set_default.clicked.connect(self.template_set_default)
        b_save_new.clicked.connect(self.template_save_as)
        b_delete.clicked.connect(self.template_delete_selected)

        return w

    def _hbox(self, widgets):
        w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(6)
        for it in widgets:
            l.addWidget(it)
        l.addStretch(1)
        return w
    
    def setWheelEventForControls(self):
    # 禁用输入框、选择框等的滚轮事件
        self.edt_text.installEventFilter(self)
        self.font_combo.installEventFilter(self)
        self.spin_font.installEventFilter(self)
        self.chk_bold.installEventFilter(self)
        self.chk_italic.installEventFilter(self)
        self.btn_text_color.installEventFilter(self)
        self.slider_opacity.installEventFilter(self)
        self.combo_type.installEventFilter(self)

    def eventFilter(self, obj, event):
        # 仅对鼠标滚轮事件进行处理
        if event.type() == QEvent.Wheel:
            if isinstance(obj, (QLineEdit, QComboBox, QSpinBox, QSlider, QCheckBox)):
                # 阻止滚轮事件传播，避免误操作
                event.ignore()
                return True  # 不传递给默认事件处理
        return super().eventFilter(obj, event)


    # ---------- Theme ----------
    def apply_fusion_theme(self):
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


    # ---------- 事件 ----------
    def closeEvent(self, e):
        try:
            self.save_last_session()
        except Exception:
            pass
        super().closeEvent(e)

    # ===== 窗口级拖拽兜底：把文件/文件夹拖到窗口任意处都能导入 =====
    def dragEnterEvent(self, e):
        if self._dnd_has_supported_urls(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._dnd_has_supported_urls(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        paths = self._dnd_extract_paths(e)
        if paths:
            self.add_images(paths)
            # 显式声明本次为复制动作，避免某些环境下 Qt 忽略
            e.setDropAction(Qt.CopyAction)
            e.acceptProposedAction()
        else:
            e.ignore()

    def _dnd_has_supported_urls(self, e) -> bool:
        md = e.mimeData()
        if not md.hasUrls():
            return False
        for u in md.urls():
            p = Path(u.toLocalFile())
            if p.is_dir():
                return True
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                return True
        return False

    def _dnd_extract_paths(self, e) -> list[str]:
        md = e.mimeData()
        if not md.hasUrls():
            return []
        paths = []
        for u in md.urls():
            p = Path(u.toLocalFile())
            if not p.exists():
                continue
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                paths.append(str(p))
            elif p.is_dir():
                # 仅扫描一层
                try:
                    for name in os.listdir(p):
                        f = p / name
                        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                            paths.append(str(f))
                except Exception:
                    pass
        return paths

    # ---------- 业务 ----------
    def action_import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)"
        )
        if files:
            self.add_images(files)

    def action_import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not d:
            return
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
        self.preview.setImage(QImage(), "")
        self.current_index = -1
        self.statusBar().showMessage("已清空列表")

    def add_images(self, paths):
        added = 0
        for p in paths:
            path = Path(p)
            if not path.exists() or path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            if any(img["path"] == str(path) for img in self.images):
                continue
            img = QImage(str(path))
            if img.isNull():
                continue
            self.images.append({"path": str(path), "img": img, "w": img.width(), "h": img.height()})
            item = QListWidgetItem(QIcon(QPixmap.fromImage(img).scaled(112,84, Qt.KeepAspectRatio, Qt.SmoothTransformation)),
                                   path.name)
            item.setToolTip(str(path))
            self.list.addItem(item)
            added += 1

        if added > 0 and self.current_index == -1:
            self.list.setCurrentRow(0)

        self.statusBar().showMessage(f"已导入 {added} 张图片（总计 {len(self.images)}）")

    def on_list_selection(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self.images):
            return
        self.current_index = row
        data = self.images[row]
        self.preview.setImage(data["img"], data["path"])
        # 切换预览时刷新九宫格高亮
        self.update_anchor_buttons()

    def on_type_changed(self):
        typ = "text" if self.combo_type.currentIndex() == 0 else "image"
        self.settings["watermark_type"] = typ
        self.gb_text.setVisible(typ == "text")
        self.gb_image.setVisible(typ == "image")
        self.update_preview()

    def on_settings_changed(self, *args):
        # 文本
        self.settings["text"] = self.edt_text.text()
        self.settings["font_family"] = self.font_combo.currentFont().family()
        self.settings["font_px"] = self.spin_font.value()
        self.settings["bold"] = self.chk_bold.isChecked()
        self.settings["italic"] = self.chk_italic.isChecked()
        self.settings["text_color"] = self.btn_text_color.color().name(QColor.HexRgb)
        self.settings["opacity"] = self.slider_opacity.value()
        # 描边/阴影
        self.settings["outline"] = self.chk_outline.isChecked()
        self.settings["outline_px"] = self.spin_outline.value()
        self.settings["outline_color"] = self.btn_outline_color.color().name(QColor.HexRgb)
        self.settings["shadow"] = self.chk_shadow.isChecked()
        self.settings["shadow_dx"] = self.spin_shadow_dx.value()
        self.settings["shadow_dy"] = self.spin_shadow_dy.value()
        self.settings["shadow_color"] = self.btn_shadow_color.color().name(QColor.HexArgb)

        # 图片水印
        self.settings["image_scale_percent"] = self.slider_img_scale.value()
        self.settings["image_opacity"] = self.slider_img_opacity.value()

        # 旋转
        self.settings["rotation_deg"] = self.slider_rot.value()

        # 导出
        ex = self.settings["export"]
        ex["output_dir"] = self.edt_outdir.text().strip()
        ex["prevent_export_to_source"] = self.chk_prevent.isChecked()
        ex["out_format"] = self.combo_format.currentText()
        ex["jpeg_quality"] = self.slider_quality.value()
        mode_str = self.combo_resize.currentText()
        ex["resize_mode"] = {"不缩放":"none","按宽度":"width","按高度":"height","按百分比":"percent"}[mode_str]
        ex["resize_value"] = self.spin_resize.value()
        ex["name_rule"] = {"保留原文件名":"keep","添加前缀":"prefix","添加后缀":"suffix"}[self.combo_name_rule.currentText()]
        ex["name_value"] = self.edt_name_value.text()

        self.update_jpeg_controls()
        self.update_preview()

    def update_jpeg_controls(self):
        is_jpeg = self.combo_format.currentText() == "JPEG"
        self.slider_quality.setEnabled(is_jpeg)
        self.lbl_quality.setEnabled(is_jpeg)

    def pick_watermark_image(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择水印图片（建议PNG透明）", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if f:
            self.settings["image_path"] = f
            self.lbl_wm_img.setText(Path(f).name)
            self.update_preview()

    def pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if d:
            self.edt_outdir.setText(d)
            self.on_settings_changed()

    def on_anchor_clicked(self, key):
        # 1) 设置预设锚点
        self.settings["anchor"] = key

        # 2) 将当前锚点对应的“实际显示位置”同步为自定义比例坐标（为下一次拖拽做准备）
        if 0 <= self.current_index < len(self.images):
            base_img = self.images[self.current_index]["img"]
            bw, bh = base_img.width(), base_img.height()
            if bw > 0 and bh > 0:
                # 使用当前基图尺寸与当前水印尺寸计算左上角位置（原图坐标系）
                x_px, y_px = self.calc_anchor_top_left(key, bw, bh)
                # 同步到 pos_ratio，保证后续拖拽“从所见位置开始”
                self.settings["pos_ratio_x"] = x_px / bw
                self.settings["pos_ratio_y"] = y_px / bh

        self.update_anchor_buttons()
        self.update_preview()


    def update_anchor_buttons(self):
        cur = self.settings.get("anchor", "custom")
        for k, b in self.grid_btns.items():
            b.setStyleSheet("QToolButton{background:#444;} QToolButton:hover{background:#555;}")
            if k == cur:
                b.setStyleSheet("QToolButton{background:#4da3ff; color:#000; font-weight:bold;}")

    def on_preview_pos_changed(self, x_ratio, y_ratio):
        self.settings["pos_ratio_x"] = float(x_ratio)
        self.settings["pos_ratio_y"] = float(y_ratio)
        # 拖拽后即处于 custom
        self.settings["anchor"] = "custom"
        self.update_anchor_buttons()
        self.update_preview()

    # ---------- 预览绘制 ----------
    def update_preview(self):
        # 在重绘前，先更新一次水印缓存，避免 paintEvent 里再触发计算
        self.update_preview_watermark()
        self.preview.update()

    def update_preview_watermark(self):
        """生成预览使用的水印 QPixmap（等比例缩放以匹配预览比例）"""
        if self.current_index < 0 or self.current_index >= len(self.images):
            self.preview.setPreviewWatermarkPixmap(QPixmap())
            return
        data = self.images[self.current_index]
        base_img: QImage = data["img"]
        base_w, base_h = base_img.width(), base_img.height()
        if base_w == 0 or base_h == 0:
            self.preview.setPreviewWatermarkPixmap(QPixmap()); return

        # 先生成“原图尺寸语义”的水印图像（用于导出），再按预览比例缩放
        wm_img = self.build_watermark_image_for_base(base_w, base_h)
        if wm_img.isNull():
            self.preview.setPreviewWatermarkPixmap(QPixmap()); return

        # 应用旋转
        wm_img = self.apply_rotation(wm_img, self.settings["rotation_deg"])

        # 缩放到预览比例
        scale = self.preview._scale_factor
        prev_pm = QPixmap.fromImage(wm_img).scaled(
            int(wm_img.width() * scale),
            int(wm_img.height() * scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.preview.setPreviewWatermarkPixmap(prev_pm)

    def build_watermark_image_for_base(self, base_w: int, base_h: int) -> QImage:
        """根据当前设置，基于“原图尺寸概念”生成水印图像（透明背景），供导出与预览二次缩放使用"""
        typ = self.settings.get("watermark_type", "text")
        if typ == "text":
            text = self.settings.get("text", "").strip()
            if not text:
                return QImage()
            font = QFont(self.settings.get("font_family", QFont().family()))
            font.setPixelSize(int(self.settings.get("font_px", 48)))
            font.setBold(bool(self.settings.get("bold", False)))
            font.setItalic(bool(self.settings.get("italic", False)))

            # 先用临时画布测量文本尺寸
            tmp = QImage(2,2, QImage.Format_ARGB32_Premultiplied); tmp.fill(Qt.transparent)
            p = QPainter(tmp); p.setFont(font)
            metrics = p.fontMetrics()
            text_rect = metrics.boundingRect(text)
            p.end()

            w = max(2, text_rect.width() + 8)
            h = max(2, text_rect.height() + 8)
            img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            p.setFont(font)

            # 构造文本路径更易实现描边
            path = QPainterPath()
            baseline = metrics.ascent() + 4  # 微调基线
            path.addText(4, baseline, font, text)

            # 阴影
            if self.settings.get("shadow", True):
                dx = int(self.settings.get("shadow_dx", 2))
                dy = int(self.settings.get("shadow_dy", 2))
                shadow_color = QColor(self.settings.get("shadow_color", "#80000000"))
                p.setPen(Qt.NoPen)
                p.setBrush(shadow_color)
                p.drawPath(path.translated(dx, dy))

            # 描边
            if self.settings.get("outline", True):
                outline_px = int(self.settings.get("outline_px", 2))
                outline_color = QColor(self.settings.get("outline_color", "#000000"))
                pen = QPen(outline_color, outline_px, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)

            # 填充
            tc = QColor(self.settings.get("text_color", "#FFFFFF"))
            opacity = clamp(self.settings.get("opacity", 70) / 100.0, 0.0, 1.0)
            fill = QColor(tc.red(), tc.green(), tc.blue(), int(255 * opacity))
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPath(path)
            p.end()
            return img

        else:  # image watermark
            path = self.settings.get("image_path", "")
            if not path or not Path(path).exists():
                return QImage()
            src = QImage(path)
            if src.isNull():
                return QImage()
            # 缩放（相对原始水印）
            scale_percent = clamp(self.settings.get("image_scale_percent", 40), 1, 1000)
            new_w = max(1, int(src.width() * scale_percent / 100.0))
            new_h = max(1, int(src.height() * scale_percent / 100.0))
            scaled = src.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

            # 透明度
            opacity = clamp(self.settings.get("image_opacity", 70) / 100.0, 0.0, 1.0)
            if opacity < 1.0:
                # 应用整体透明度到图像
                tmp = QImage(scaled.size(), QImage.Format_ARGB32_Premultiplied)
                tmp.fill(Qt.transparent)
                p = QPainter(tmp)
                p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
                p.setOpacity(opacity)
                p.drawImage(0, 0, scaled)
                p.end()
                scaled = tmp
            return scaled

    def apply_rotation(self, img: QImage, deg: int) -> QImage:
        if img.isNull() or deg % 360 == 0:
            return img
        pm = QPixmap.fromImage(img)
        tr = QTransform().rotate(deg)
        pm2 = pm.transformed(tr, Qt.SmoothTransformation)
        return pm2.toImage()

    # anchor 计算：返回针对“原图坐标系”的左上角像素
    def calc_anchor_top_left(self, anchor: str, base_w: int, base_h: int,
                             for_preview=False, wm_preview_size: QSize=None) -> tuple[int, int]:
        # 构建水印在原图坐标下的尺寸（未旋转），但我们已在预览阶段将旋转后的尺寸传入（for_preview==True）
        if for_preview and wm_preview_size is not None:
            wm_w = wm_preview_size.width() / self.preview._scale_factor
            wm_h = wm_preview_size.height() / self.preview._scale_factor
        else:
            wm = self.build_watermark_image_for_base(base_w, base_h)
            wm = self.apply_rotation(wm, self.settings.get("rotation_deg", 0))
            wm_w, wm_h = wm.width(), wm.height()

        margin = 12  # 像素
        if anchor == "tl":
            x = margin; y = margin
        elif anchor == "tc":
            x = (base_w - wm_w)/2; y = margin
        elif anchor == "tr":
            x = base_w - wm_w - margin; y = margin
        elif anchor == "cl":
            x = margin; y = (base_h - wm_h)/2
        elif anchor == "cc":
            x = (base_w - wm_w)/2; y = (base_h - wm_h)/2
        elif anchor == "cr":
            x = base_w - wm_w - margin; y = (base_h - wm_h)/2
        elif anchor == "bl":
            x = margin; y = base_h - wm_h - margin
        elif anchor == "bc":
            x = (base_w - wm_w)/2; y = base_h - wm_h - margin
        elif anchor == "br":
            x = base_w - wm_w - margin; y = base_h - wm_h - margin
        else:
            # custom
            x = float(self.settings.get("pos_ratio_x", 0.5)) * base_w
            y = float(self.settings.get("pos_ratio_y", 0.5)) * base_h
        return int(x), int(y)

    # ---------- 导出 ----------
    def ensure_outdir_valid(self, src_path: str) -> tuple[bool, str]:
        outdir = self.settings["export"]["output_dir"]
        if not outdir:
            return False, "请先在“导出”页选择输出文件夹。"
        out = Path(outdir)
        out.mkdir(parents=True, exist_ok=True)

        if self.settings["export"]["prevent_export_to_source"]:
            src_dir = str(Path(src_path).parent.resolve())
            out_dir = str(out.resolve())
            if src_dir == out_dir:
                return False, "为防止覆盖原图，当前禁止导出到原文件夹。请更换输出文件夹或取消该限制。"
        return True, ""

    def make_output_name(self, src_path: str) -> str:
        ex = self.settings["export"]
        rule = ex.get("name_rule", "suffix")
        val = ex.get("name_value", "_watermarked")
        base = Path(src_path).stem
        if rule == "keep":
            newname = base
        elif rule == "prefix":
            newname = f"{val}{base}"
        else:
            newname = f"{base}{val}"

        ext = ex.get("out_format", "PNG").lower()
        if ext == "jpeg":
            ext = "jpg"
        return newname + "." + ext

    def compute_export_size(self, w: int, h: int) -> tuple[int, int]:
        ex = self.settings["export"]
        mode = ex.get("resize_mode", "none")
        val = int(ex.get("resize_value", 100))
        if mode == "width":
            nw = max(1, val)
            nh = max(1, int(h * nw / w))
        elif mode == "height":
            nh = max(1, val)
            nw = max(1, int(w * nh / h))
        elif mode == "percent":
            nw = max(1, int(w * val / 100.0))
            nh = max(1, int(h * val / 100.0))
        else:
            nw, nh = w, h
        return nw, nh

    def export_current(self):
        if self.current_index < 0 or self.current_index >= len(self.images):
            QMessageBox.warning(self, "提示", "请先导入并选择一张图片。")
            return
        src = self.images[self.current_index]["path"]
        ok, msg = self.ensure_outdir_valid(src)
        if not ok:
            QMessageBox.warning(self, "输出文件夹无效", msg)
            return
        outdir = Path(self.settings["export"]["output_dir"])
        fn = self.make_output_name(src)
        outpath = outdir / fn
        try:
            self.export_one(src, outpath)
            self.statusBar().showMessage(f"导出成功：{human_path(outpath)}")
            QMessageBox.information(self, "成功", f"已导出：{human_path(outpath)}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def export_all(self):
        if not self.images:
            QMessageBox.warning(self, "提示", "请先导入图片。")
            return
        first_src = self.images[0]["path"]
        ok, msg = self.ensure_outdir_valid(first_src)
        if not ok:
            QMessageBox.warning(self, "输出文件夹无效", msg)
            return
        outdir = Path(self.settings["export"]["output_dir"])
        N = len(self.images)

        prog = QProgressDialog("正在批量导出...", "取消", 0, N, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(400)

        success = 0
        for i, data in enumerate(self.images, start=1):
            if prog.wasCanceled():
                break
            prog.setValue(i-1)
            src = data["path"]
            outname = self.make_output_name(src)
            outpath = outdir / outname
            try:
                self.export_one(src, outpath)
                success += 1
            except Exception as e:
                # 遇错继续
                print(f"导出失败: {src} -> {e}")
            self.progress.setValue(int(i*100/N))
            QApplication.processEvents()
        prog.setValue(N)
        QMessageBox.information(self, "批量完成", f"成功导出 {success} / {N} 张。")
        self.statusBar().showMessage(f"成功导出 {success} / {N} 张。")

    def export_one(self, src_path: str, out_path: Path):
        base = QImage(src_path)
        if base.isNull():
            raise RuntimeError(f"无法读取图片：{src_path}")
        # 尺寸调整
        nw, nh = self.compute_export_size(base.width(), base.height())
        if (nw, nh) != (base.width(), base.height()):
            base = base.scaled(nw, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # 构建“基于当前 base 尺寸”的水印图像
        wm = self.build_watermark_image_for_base(base.width(), base.height())
        wm = self.apply_rotation(wm, self.settings.get("rotation_deg", 0))
        if wm.isNull():
            # 若未设置水印，直接按导出格式保存
            self.save_image(base, out_path)
            return

        # 位置
        anchor = self.settings.get("anchor", "custom")
        if anchor != "custom":
            x, y = self.calc_anchor_top_left(anchor, base.width(), base.height())
        else:
            x_ratio = float(self.settings.get("pos_ratio_x", 0.5))
            y_ratio = float(self.settings.get("pos_ratio_y", 0.5))
            # 注意：pos_ratio 是基于“原图”的，导出时我们已将 base 变为缩放后的，
            # 但 pos_ratio 本质是相对比例，因此仍可直接乘以当前 base 尺寸
            x = int(x_ratio * base.width())
            y = int(y_ratio * base.height())

            # 限制不越界
            x = clamp(x, 0, max(0, base.width()-wm.width()))
            y = clamp(y, 0, max(0, base.height()-wm.height()))

        # 合成
        out = QImage(base.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.drawImage(0, 0, base)
        p.drawImage(x, y, wm)
        p.end()

        self.save_image(out, out_path)

    def save_image(self, img: QImage, out_path: Path):
        fmt = self.settings["export"]["out_format"].upper()
        if fmt == "JPEG":
            # 透明背景合成白底（或可改为黑/自定义）
            if img.hasAlphaChannel():
                bg = QImage(img.size(), QImage.Format_RGB888)
                bg.fill(Qt.white)
                p = QPainter(bg)
                p.drawImage(0, 0, img)
                p.end()
                img = bg
            quality = int(self.settings["export"]["jpeg_quality"])
            img.save(str(out_path), "JPEG", quality)
        else:
            # PNG 保持透明
            img.save(str(out_path), "PNG")

    # ---------- 模板 ----------
    def refresh_template_list(self):
        self.template_list.clear()
        for f in sorted(templates_dir().glob("*.json")):
            self.template_list.addItem(f.stem)

    def template_save_as(self):
        """
        在 templates/ 下保存当前设置为新模板。
        不用文件选择器：弹出名称输入框，生成 {name}.json。
        """
        tdir = templates_dir()
        # 询问模板名
        name, ok = QInputDialog.getText(self, "保存为新模板", "模板名称（不含扩展名）：")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "提示", "名称不能为空。")
            return

        p = (tdir / name).with_suffix(".json")
        if p.exists():
            ret = QMessageBox.question(self, "覆盖确认", f"模板 {p.name} 已存在，是否覆盖？",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        try:
            self._save_settings_json(p)
            self.refresh_template_list()
            QMessageBox.information(self, "成功", f"模板已保存：{p.name}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")


    def template_load_selected(self):
        """从左侧列表选择并加载模板"""
        item = self.template_list.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先在列表中选择一个模板。")
            return
        p = templates_dir() / f"{item.text()}.json"
        if not p.exists():
            QMessageBox.warning(self, "提示", f"模板不存在：{p}")
            return
        try:
            self._load_settings_json(p)
            self.apply_settings_to_ui()
            self.update_preview()
            QMessageBox.information(self, "成功", f"已加载模板：{item.text()}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败：{e}")

    def template_load_from_file(self):
        """通过文件选择器加载任意模板（默认定位 templates/）"""
        f, ok = QFileDialog.getOpenFileName(self, "选择模板文件", str(templates_dir()), "Template (*.json)")
        if not ok or not f:
            return
        p = Path(f)
        try:
            self._load_settings_json(p)
            self.apply_settings_to_ui()
            self.update_preview()
            QMessageBox.information(self, "成功", f"已加载模板：{p.name}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败：{e}")

    def template_set_default(self):
        """将当前设置保存为默认模板 default.json"""
        p = default_template_path()
        try:
            self._save_settings_json(p)
            QMessageBox.information(self, "成功", f"已设为默认模板：{p.name}")
            self.refresh_template_list()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")

    def template_open_folder(self):
        """打开 templates 文件夹"""
        tdir = templates_dir()
        try:
            if platform.system() == "Windows":
                os.startfile(str(tdir))
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(tdir)])
            else:
                subprocess.run(["xdg-open", str(tdir)])
        except Exception as e:
            QMessageBox.warning(self, "提示", f"无法打开文件夹：{tdir}\n{e}")

    def template_delete_selected(self):
        """删除列表中所选模板"""
        item = self.template_list.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先选择一个模板。")
            return
        p = templates_dir() / f"{item.text()}.json"
        try:
            p.unlink(missing_ok=True)
            self.refresh_template_list()
            QMessageBox.information(self, "成功", "模板已删除。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除失败：{e}")

    def _save_settings_json(self, p: Path):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=2)

    def _load_settings_json(self, p: Path):
        with open(p, "r", encoding="utf-8") as f:
            self.settings = json.load(f)

    def save_last_session(self):
        p = last_session_path()
        self._save_settings_json(p)

    def load_last_session(self):
        """
        启动时的加载策略：
        1) 若存在 last_session.json，优先加载；
        2) 否则若存在 default.json，加载默认模板；
        3) 若都不存在，创建 default.json（用当前 settings）并保存一次 last_session。
        """
        lp = last_session_path()
        dp = default_template_path()
        try:
            if lp.exists():
                self._load_settings_json(lp)
                self.apply_settings_to_ui()
                return True
            elif dp.exists():
                self._load_settings_json(dp)
                self.apply_settings_to_ui()
                # 同时把默认模板内容写入 last_session 作为起点
                self._save_settings_json(lp)
                return True
            else:
                # 首次运行：以当前 settings 生成一个 default 与 last_session
                self._save_settings_json(dp)
                self._save_settings_json(lp)
                return True
        except Exception:
            return False

    def apply_settings_to_ui(self):
        # 类型
        self.combo_type.setCurrentIndex(0 if self.settings.get("watermark_type","text")=="text" else 1)
        # 文本
        self.edt_text.setText(self.settings.get("text",""))
        self.font_combo.setCurrentFont(QFont(self.settings.get("font_family", QFont().family())))
        self.spin_font.setValue(int(self.settings.get("font_px", 128)))
        self.chk_bold.setChecked(bool(self.settings.get("bold", False)))
        self.chk_italic.setChecked(bool(self.settings.get("italic", False)))
        self.btn_text_color.setColor(QColor(self.settings.get("text_color","#FFFFFF")))
        self.slider_opacity.setValue(int(self.settings.get("opacity", 70)))
        self.chk_outline.setChecked(bool(self.settings.get("outline", True)))
        self.spin_outline.setValue(int(self.settings.get("outline_px", 2)))
        self.btn_outline_color.setColor(QColor(self.settings.get("outline_color","#000000")))
        self.chk_shadow.setChecked(bool(self.settings.get("shadow", True)))
        self.spin_shadow_dx.setValue(int(self.settings.get("shadow_dx",2)))
        self.spin_shadow_dy.setValue(int(self.settings.get("shadow_dy",2)))
        self.btn_shadow_color.setColor(QColor(self.settings.get("shadow_color","#80000000")))
        # 图片
        pth = self.settings.get("image_path","")
        self.lbl_wm_img.setText(Path(pth).name if pth else "未选择")
        self.slider_img_scale.setValue(int(self.settings.get("image_scale_percent",40)))
        self.slider_img_opacity.setValue(int(self.settings.get("image_opacity",70)))
        # 旋转
        deg = int(self.settings.get("rotation_deg", 0))
        self.slider_rot.setValue(deg)
        self.lbl_rot.setText(f"{deg}°")
        # 导出
        ex = self.settings.get("export", {})
        self.edt_outdir.setText(ex.get("output_dir",""))
        self.chk_prevent.setChecked(bool(ex.get("prevent_export_to_source", True)))
        self.combo_format.setCurrentText(ex.get("out_format","PNG"))
        self.slider_quality.setValue(int(ex.get("jpeg_quality",90)))
        self.combo_resize.setCurrentText({"none":"不缩放","width":"按宽度","height":"按高度","percent":"按百分比"}.get(ex.get("resize_mode","none"),"不缩放"))
        self.spin_resize.setValue(int(ex.get("resize_value",100)))
        self.combo_name_rule.setCurrentText({"keep":"保留原文件名","prefix":"添加前缀","suffix":"添加后缀"}.get(ex.get("name_rule","suffix"),"添加后缀"))
        self.edt_name_value.setText(ex.get("name_value","_watermarked"))
        self.update_anchor_buttons()
        self.update_jpeg_controls()

    # ---------- 其它 ----------
    def about(self):
        QMessageBox.information(self, "关于", f"{APP_NAME}\n\n使用 PySide6 构建的本地水印工具。\n支持批量、模板、预览拖拽、九宫格布局、旋转等。")

# ---------- 应用入口 ----------
def main():

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
