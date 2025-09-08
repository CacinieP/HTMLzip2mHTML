#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将包含 HTML 与其资源（主要是图片）的 ZIP 压缩包打包为 MHTML（.mhtml/.mht）。

用法示例：
    python mhtml_from_zip.py --zip input.zip --out output.mhtml
    python mhtml_from_zip.py --zip input.zip --out output.mhtml --html index.html

说明：
- 默认会自动选择 ZIP 里第一个 .html/.htm 文件作为主 HTML；如有多个可用 --html 指定。
- 会扫描 <img src="..."> 的资源引用，凡是 ZIP 内存在的相对路径图片，都会内联为 MHTML 的附件，并将 HTML 中的引用替换为 cid:xxx。
- 目前聚焦图片（img/src）；如需扩展到 CSS/JS 可按相同思路添加。
"""

import argparse
import codecs
import mimetypes
import os
import re
import sys
import uuid
import zipfile
from io import BytesIO
from typing import Dict, List, Tuple

from email import encoders, policy
from email.generator import BytesGenerator
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import unquote


def detect_encoding(html_bytes: bytes) -> str:
    """尽力从字节流中判断编码，优先 BOM，然后 <meta charset=...>，默认 utf-8。"""
    # BOM 检测
    if html_bytes.startswith(codecs.BOM_UTF8):
        return "utf-8"
    if html_bytes.startswith(codecs.BOM_UTF16_LE):
        return "utf-16le"
    if html_bytes.startswith(codecs.BOM_UTF16_BE):
        return "utf-16be"

    # 在前几 KB 中查找 meta charset
    head = html_bytes[:8192].decode("ascii", errors="ignore")
    m = re.search(r"charset=[\"\']?([A-Za-z0-9_\-]+)", head, re.I)
    if m:
        return m.group(1).lower()

    return "utf-8"


essential_img_src_re = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*)([\"\'])(.+?)(\2)", re.I)
external_scheme_re = re.compile(r"^(https?:|data:|cid:|//)", re.I)


def normalize_zip_path(p: str) -> str:
    # ZIP 内部路径统一使用正斜杠
    return p.replace("\\", "/")


def resolve_rel_path(base_html: str, ref_path: str) -> str:
    # 解析相对路径到 ZIP 内部路径；支持以 / 或 \\ 开头的“根相对”写法
    base_dir = os.path.dirname(base_html)
    # 去掉可能的前导斜杠，视为相对 ZIP 根
    if ref_path.startswith(("/", "\\")):
        joined = os.path.normpath(ref_path.lstrip("/\\"))
    else:
        joined = os.path.normpath(os.path.join(base_dir, ref_path))
    return normalize_zip_path(joined)


def pick_main_html(names: List[str]) -> str:
    for n in names:
        ln = n.lower()
        if ln.endswith(".html") or ln.endswith(".htm"):
            return n
    return ""


def build_mhtml(html_text: str, html_name: str, resources: List[Dict], charset: str) -> bytes:
    # 构建 multipart/related 的 MHTML
    root = MIMEMultipart("related")
    root["MIME-Version"] = "1.0"
    # 指定根类型 text/html，兼容性更好
    root.set_param("type", "text/html")

    # 主 HTML part
    html_part = MIMEText(html_text, "html", _charset=charset)
    # 设置 Content-Location 以便阅读器识别根文档
    html_part.add_header("Content-Location", os.path.basename(html_name) or "index.html")
    root.attach(html_part)

    # 资源 parts（图片等）
    for res in resources:
        mime = res.get("mime", "application/octet-stream")
        maintype, subtype = (mime.split("/", 1) + ["octet-stream"])[:2]
        part = MIMEBase(maintype, subtype)
        part.set_payload(res["data"]) 
        encoders.encode_base64(part)
        part.add_header("Content-ID", f"<{res['cid']}>")
        # 使用原始相对路径作为 Content-Location，便于回溯
        part.add_header("Content-Location", res.get("name", ""))
        root.attach(part)

    # 生成字节（使用 SMTP policy 产出 CRLF 换行，更贴近 MHTML 期望）
    bio = BytesIO()
    gen = BytesGenerator(bio, policy=policy.SMTP)
    gen.flatten(root)
    return bio.getvalue()


def find_leaf_zip_with_html(zip_bytes: bytes, max_depth: int = 10) -> bytes:
    """
    在可能嵌套的 ZIP 字节流中，递归查找包含 .html/.htm 的最内层 ZIP。
    返回该 ZIP 的字节流；如未找到返回 None。
    """
    seen = set()

    def helper(b: bytes, depth: int):
        if depth > max_depth:
            return None
        try:
            with zipfile.ZipFile(BytesIO(b), 'r') as zf:
                names = [normalize_zip_path(n) for n in zf.namelist()]
                # 如果当前层已有 HTML，则认为此处为叶子
                if any(n.lower().endswith((".html", ".htm")) for n in names):
                    return b
                # 否则尝试深入所有子 ZIP
                for n in names:
                    if not n.lower().endswith('.zip'):
                        continue
                    try:
                        child = zf.read(n)
                    except KeyError:
                        continue
                    key = (n, len(child))
                    if key in seen:
                        continue
                    seen.add(key)
                    res = helper(child, depth + 1)
                    if res is not None:
                        return res
        except zipfile.BadZipFile:
            return None
        return None

    return helper(zip_bytes, 0)


def process_zip(zip_path: str, output_path: str, html_name_override: str = None) -> Tuple[str, List[str]]:
    """从 ZIP（支持嵌套 ZIP）读取 HTML，内联图片并生成 MHTML。
    返回 (主HTML路径, 内联图片列表)。"""
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(f"ZIP 不存在: {zip_path}")

    # 读取最外层 ZIP 字节，并递归定位包含 HTML 的最内层 ZIP
    with open(zip_path, 'rb') as f:
        root_bytes = f.read()

    leaf_bytes = find_leaf_zip_with_html(root_bytes)
    if leaf_bytes is None:
        raise RuntimeError("未在 ZIP 或其嵌套 ZIP 中找到 .html/.htm 文件，请使用 --html 指定主 HTML 文件名或检查压缩包结构")

    with zipfile.ZipFile(BytesIO(leaf_bytes), "r") as zf:
        names = [normalize_zip_path(n) for n in zf.namelist()]

        # 选择主 HTML
        if html_name_override:
            if html_name_override in names:
                html_name = html_name_override
            else:
                raise RuntimeError(f"指定的 --html 未在 ZIP 中找到: {html_name_override}")
        else:
            html_name = pick_main_html(names)
            if not html_name:
                raise RuntimeError("未在 ZIP 中找到 .html/.htm 文件")

        html_bytes = zf.read(html_name)
        charset = detect_encoding(html_bytes)
        html_text = html_bytes.decode(charset, errors="replace")

        # 构建 ZIP 里路径到实际条目的映射
        name_set = set(names)
        name_map = {n: n for n in names}

        # 查找并替换 <img src="...">
        resources: List[Dict] = []
        cid_map: Dict[str, str] = {}
        inlined: List[str] = []

        def replace_img_src(m: re.Match) -> str:
            prefix, quote, path, _ = m.groups()
            # 去除片段与查询串
            path_core = path.split("#", 1)[0]
            path_core = path_core.split("?", 1)[0]
            if external_scheme_re.match(path_core):
                return m.group(0)

            # 尝试原始与 URL 解码后的两种候选路径
            candidates: List[str] = [path_core]
            try:
                decoded = unquote(path_core)
                if decoded != path_core:
                    candidates.append(decoded)
            except Exception:
                pass

            for cand in candidates:
                rel = resolve_rel_path(html_name, cand)
                if rel in name_set:
                    if rel not in cid_map:
                        cid = uuid.uuid4().hex + "@mhtml"
                        data = zf.read(name_map[rel])
                        mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
                        resources.append({
                            "name": rel,
                            "cid": cid,
                            "data": data,
                            "mime": mime,
                        })
                        cid_map[rel] = cid
                        inlined.append(rel)
                    return f"{prefix}{quote}cid:{cid_map[rel]}{quote}"

            return m.group(0)

        new_html_text = essential_img_src_re.sub(replace_img_src, html_text)

        mhtml_bytes = build_mhtml(new_html_text, html_name, resources, charset)
        with open(output_path, "wb") as f:
            f.write(mhtml_bytes)

        return html_name, inlined


def main():
    parser = argparse.ArgumentParser(description="将包含 HTML 与图片的 ZIP 打包为 MHTML")
    parser.add_argument("--zip", dest="zip_path", help="输入 ZIP 路径（单文件模式）")
    parser.add_argument("--out", dest="out_path", help="输出 MHTML 路径（仅单文件模式）")
    parser.add_argument("--html", dest="html_name", default=None, help="ZIP 中主 HTML 的相对路径（可选，单文件模式）")
    parser.add_argument("--batch", action="store_true", help="批量模式：处理脚本所在目录（或 --dir 指定目录）中的所有 ZIP")
    parser.add_argument("--dir", dest="dir_path", default=None, help="批量模式扫描目录（默认：脚本所在目录）")
    args = parser.parse_args()

    def run_single(zip_path: str, out_path: str, html_name: str = None):
        html_name_res, inlined = process_zip(zip_path, out_path, html_name)
        print(f"主 HTML: {html_name_res}")
        if inlined:
            print("已内联图片：")
            for p in inlined:
                print(f"  - {p}")
        else:
            print("未发现可内联的图片资源（或引用为外链/data URI）")
        print(f"生成完成: {out_path}")

    # 决定模式：显式 --batch 或 未提供 --zip/--out 时进入批量模式
    batch_mode = args.batch or (not args.zip_path and not args.out_path)

    if batch_mode:
        # 扫描目录：优先 --dir，否则脚本所在目录
        scan_dir = os.path.abspath(args.dir_path) if args.dir_path else os.path.dirname(os.path.abspath(__file__))
        if not os.path.isdir(scan_dir):
            print(f"错误: 指定目录不存在: {scan_dir}", file=sys.stderr)
            sys.exit(1)

        # 找到所有 .zip（不区分大小写）
        zip_files = [fn for fn in os.listdir(scan_dir) if fn.lower().endswith('.zip')]
        if not zip_files:
            print(f"未在目录中找到 ZIP 文件: {scan_dir}")
            sys.exit(0)

        print(f"批量处理目录: {scan_dir}")
        total = len(zip_files)
        ok = 0
        for fn in zip_files:
            zip_path = os.path.join(scan_dir, fn)
            base, _ = os.path.splitext(fn)
            out_path = os.path.join(scan_dir, base + ".mhtml")  # 保持 zip 前缀名不变
            print(f"处理: {zip_path} -> {out_path}")
            try:
                run_single(zip_path, out_path, None)
                ok += 1
            except Exception as e:
                print(f"错误处理 {zip_path}: {e}", file=sys.stderr)
        print(f"批量完成：成功 {ok}/{total}")
        sys.exit(0 if ok > 0 else 1)

    else:
        # 单文件模式：需要 --zip 与 --out
        if not args.zip_path or not args.out_path:
            print("错误: 单文件模式需要同时提供 --zip 与 --out", file=sys.stderr)
            sys.exit(1)
        try:
            run_single(args.zip_path, args.out_path, args.html_name)
        except Exception as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()