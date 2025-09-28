# photo-watermark-cli

**photo-watermark-cli** 是一个命令行工具：批量读取图片的 **EXIF 拍摄日期（仅年月日）**，将其作为**文字水印**叠加到图片上。  
用户可设置**字体大小**、**颜色**、**位置（左上/居中/右下等）** 等参数。  
处理后的图片**统一保存到项目根目录的 `output/` 文件夹**，不会覆盖原图（文件名追加 `_wm`）。

---

## ✨ 功能特性

- 自动从 EXIF 读取拍摄日期：优先 `DateTimeOriginal` → `DateTimeDigitized` → `DateTime`；输出格式 `YYYY-MM-DD`  
- 支持**单张图片**或**目录（递归子目录）**批量处理  
- 可配置：
  - 位置：`lt`（左上）、`rt`（右上）、`lb`（左下）、`rb`（右下，默认）、`c`/`center`（居中）
  - 字体大小（`--font-size`）或**按图片短边比例自动字号**（`--auto-size`，推荐）
  - 颜色（`--color`），透明度（`--opacity`），边距（`--margin`），描边（`--stroke-width` / `--stroke-color`）
  - 字体文件（`--font`，建议中文环境指定中文字体）
- 无 EXIF 可用**文件修改时间**兜底（`--fallback-mtime`）
- **输出目录**始终为**项目根目录**下的 `output/` 文件夹（避免递归二次处理）

---

## ⚙️ 环境配置

> 仅依赖 [Pillow](https://python-pillow.org/)。建议优先使用 **Anaconda/Miniconda**；也可使用 Python 自带 **venv**。

### 方式一：Anaconda / Miniconda（推荐）
```bat
conda create -n photo-wm python=3.11 -y
conda activate photo-wm
conda install -c conda-forge pillow -y
```

> 若遇到缓存损坏或版本问题：
> ```bat
> conda clean -a -y
> conda update -n base -c defaults conda -y
> ```

### 方式二：Python venv（可选）
```bat
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS/Linux
pip install Pillow
```

---

## 🚀 使用方式（示例）

> 请先切到项目根目录，例如：`E:\Study\研一上\photo-watermark-cli`

### A. 批量处理整个目录（推荐）
```bat
python src\photo_watermark\watermark.py "E:\Study\研一上\photo-watermark-cli\tests" ^
  --auto-size 0.05 ^
  --position rb ^
  --color white ^
  --opacity 220 ^
  --stroke-width 2 --stroke-color black ^
  --font "C:\Windows\Fonts\msyh.ttc" ^
  --fallback-mtime
```
说明：
- `--auto-size 0.05` 表示字体≈“图片短边的 5%”（比固定字号更自适应，也更容易统一视觉效果）
- `--position rb` 水印在右下角；可改 `lt/rt/lb/c` 等
- `--font` 指定中文字体，避免出现方块字

### B. 处理单张图片
```bat
python src\photo_watermark\watermark.py "E:\Study\研一上\photo-watermark-cli\tests\test_img_01.jpg" ^
  --auto-size 0.05 ^
  --position center ^
  --color "#FFD700" ^
  --opacity 200 ^
  --stroke-width 2 --stroke-color "#000000" ^
  --font "C:\Windows\Fonts\msyh.ttc"
```

---

## 📖 参数说明

| 参数 | 说明 | 默认值 / 取值 |
|---|---|---|
| `path` | 输入路径（文件或目录） | 必填 |
| `--position` | 水印位置：`lt` / `rt` / `lb` / `rb` / `c`（别名：`left-top`/`top-left`/`right-bottom`/`center` 等） | `rb` |
| `--font-size` | 固定字号（像素）。当 `--auto-size` > 0 时被覆盖 | `96` |
| `--auto-size` | 自动字号（图片短边 × 比例，例：`0.05` = 5%） | `0.0`（关闭） |
| `--color` | 文字颜色，支持 `#RRGGBB` / `#RGB` / 颜色名（white/black 等） | `#FFFFFF` |
| `--opacity` | 不透明度 0–255（越小越透明） | `220` |
| `--margin` | 距边距（像素） | `20` |
| `--font` | 字体文件路径（TTF/OTF/TTC）。中文建议指定 | 自动探测，失败用默认字体 |
| `--stroke-width` | 描边宽度（像素） | `2` |
| `--stroke-color` | 描边颜色 | `#000000` |
| `--fallback-mtime` | 无 EXIF 时用文件修改时间 | 关闭 |

### 常用参数
- --position：rb/rt/lb/lt/c 等；默认 rb（右下）
- --font-size：固定字号；--auto-size：短边比例（两者二选一，后者覆盖前者）
- --color / --stroke-color：支持 #RRGGBB 或颜色名
- --opacity：0-255；--stroke-width：描边像素
- --fallback-mtime：当无 EXIF 日期时使用文件修改时间

### 示例
```bash
python src/photo_watermark/watermark.py "tests/demo" \
  --position rb --auto-size 0.12 --color "#FFFFFF" \
  --stroke-width 2 --stroke-color "#000000" --opacity 220 --fallback-mtime

---

## 📂 输出说明

- 输入是目录：结果写入**项目根目录**下的 `output/` 文件夹
- 输入是单文件：也写入**项目根目录**下的 `output/` 文件夹
- 输出文件名在原名后追加 `_wm`，例如：
  - `test_img_01.jpg` → `output/test_img_01_wm.jpg`
  - `holiday.png` → `output/holiday_wm.png`
- 原图不会被覆盖

