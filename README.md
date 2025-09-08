# HTML 文件夹（ZIP）一键整合为 MHTML

本项目提供一个实用脚本，将“HTML 文件夹及其资源（如图片）”打包成的 ZIP 压缩包整合为单个 MHTML 文件，可单个处理或批量处理同目录下的所有 ZIP。

核心脚本：<mcfile name="mhtml_from_zip.py" path="c:\Users\pc\Desktop\HTMLfolder2MHTML\mhtml_from_zip.py"></mcfile>

适用场景：当你有一个网页导出的目录（包含 .html 和 images 等资源子目录），先将该目录压缩为 .zip，然后用本脚本一键合并为一个可独立打开的 .mhtml 文件。

## 功能特性
- 支持单文件模式与批量模式（默认扫描脚本所在目录下的所有 .zip）
- 自动选择 ZIP 中第一个 .html/.htm 作为主页面，或通过 `--html` 指定具体 HTML
- 自动检测 HTML 编码（BOM、meta charset），保证字符显示正确
- 将 `<img src="...">` 引用的、位于 ZIP 内的图片内联为 MHTML 附件，并重写为 `cid:...`
- 支持嵌套 ZIP：会递归定位最内层包含 HTML 的 ZIP 后再进行处理
- 纯标准库实现，无第三方依赖

## 环境要求
- Python 3（建议 3.7+）
- Windows/macOS/Linux 皆可

## 快速开始
1) 将你的 HTML 文件夹打包为一个 ZIP（例如：`MyPage.zip`）
2) 把 ZIP 放到与脚本相同的目录
3) 执行以下任一方式：

- 批量模式（无参数或显式 `--batch`），会处理当前目录下所有 .zip：
  
  PowerShell / CMD：
  ```bash
  python mhtml_from_zip.py
  # 或
  python mhtml_from_zip.py --batch
  ```
  可指定扫描目录：
  ```bash
  python mhtml_from_zip.py --batch --dir "C:\path\to\zips"
  ```

- 单文件模式（指定输入 ZIP 与输出 MHTML 路径）：
  ```bash
  python mhtml_from_zip.py --zip "MyPage.zip" --out "MyPage.mhtml"
  ```
  若 ZIP 中有多个 HTML，使用 `--html` 指定主页面的相对路径（相对于 ZIP 根）：
  ```bash
  python mhtml_from_zip.py --zip "MyPage.zip" --out "MyPage.mhtml" --html "index.html"
  ```

## 参数说明
- `--zip`：输入 ZIP 路径（单文件模式）
- `--out`：输出 MHTML 路径（单文件模式）
- `--html`：ZIP 中主 HTML 的相对路径（可选，单文件模式）
- `--batch`：批量模式；处理指定目录（或脚本所在目录）下的所有 ZIP
- `--dir`：在批量模式下指定扫描的目录；缺省为脚本所在目录

说明：如果未提供 `--zip` 与 `--out`，脚本会自动进入批量模式。

## 输入与输出
- 输入：包含 HTML 及其资源文件（如 images 子目录内的 PNG/JPG 等）的 ZIP 压缩包
- 输出：对应的 `.mhtml` 文件
  - 批量模式下，输出文件名与 ZIP 同名（仅扩展名改为 `.mhtml`），并保存在扫描目录中
  - 单文件模式下，输出到 `--out` 所指路径
- 原 ZIP 不会被修改

## 工作原理（简述）
- 打开（并在需要时递归打开）ZIP，定位包含 `.html/.htm` 的最内层 ZIP
- 选取主 HTML（默认第一个，或按 `--html` 强制指定）并检测编码
- 解析 HTML 中的 `<img src="...">`：
  - 仅处理 ZIP 内存在的相对路径图片
  - 外链（http/https）、`data:`、`cid:` 形式保留原样
- 将匹配到的图片作为附件内联到 MHTML 中，HTML 中的 src 改写为 `cid:...`

## 限制与注意事项
- 当前仅内联 `<img src="...">` 的图片资源；CSS 背景图、外部 CSS/JS 等暂不内联（可按同思路扩展）
- 资源路径解析相对于主 HTML 文件所在目录
- 如果 ZIP 中没有发现 `.html/.htm`，会报错提示检查压缩包或使用 `--html` 指定
- 为确保能正确内联，请保证图片文件真实存在于 ZIP 内，且 src 使用相对路径

## 常见问题（FAQ）
- 问：我的是“HTML 文件夹”，不是 ZIP，如何处理？
  - 答：请先把该文件夹整体压缩为一个 ZIP（保持内部相对路径结构不变），再用本脚本转换。

- 问：输出 MHTML 中部分图片没有显示？
  - 答：常见原因有三：
    1) 图片是网络外链（http/https）或 `data:`/`cid:` 形式，脚本不会改写；
    2) src 路径不正确或图片不在 ZIP 中；
    3) 图片来自 CSS 背景或其它非 `<img src>` 引用（当前版本未内联）。

- 问：一个 ZIP 里有多个 HTML，脚本选错了主页面？
  - 答：使用 `--html` 精确指定主 HTML 的相对路径，例如：`--html pages/index.html`。

## 示例
- `ExportBlock-xxxx-Part-1.zip` 处理后得到 `ExportBlock-xxxx-Part-1.mhtml`
- 批量模式会依次处理目录中所有 `.zip`，并打印每个条目的主 HTML 及成功内联的图片列表