#!/usr/bin/env python3
"""
safe_read_pdf.py - 大容量PDF自動分割読み込みスクリプト

Claude CodeのAPI制限（約5-10MB）を回避するため、
大きなPDFを自動的に分割してテキストを抽出する。
スキャンPDFの場合は画像に変換してClaude Codeで読み込めるようにする。

使用方法:
    # テキスト抽出モード（テキストベースPDF用）
    python safe_read_pdf.py "path/to/file.pdf"

    # 画像変換モード（スキャンPDF用）★推奨
    python safe_read_pdf.py "path/to/file.pdf" --to-images --output-dir ./temp_images

出力:
    JSON形式で結果を出力
"""

import os
import sys
import json
import tempfile
import shutil
import argparse
from pathlib import Path

# サイズ閾値（MB）
DEFAULT_THRESHOLD_MB = 3.0
TARGET_CHUNK_SIZE_MB = 2.0
MAX_PAGES_PER_CHUNK = 5
TARGET_IMAGE_SIZE_MB = 2.0  # 画像1枚あたりの目標サイズ


def get_file_size_mb(file_path: str) -> float:
    """ファイルサイズをMB単位で取得"""
    return os.path.getsize(file_path) / (1024 * 1024)


def analyze_pdf(pdf_path: str) -> dict:
    """PDFを分析して情報を返す"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"error": "pypdf がインストールされていません。pip install pypdf を実行してください。"}

    file_size_mb = get_file_size_mb(pdf_path)

    try:
        reader = PdfReader(pdf_path)
        page_count = len(reader.pages)
    except Exception as e:
        return {"error": f"PDF読み込みエラー: {str(e)}"}

    # スキャンPDFか判定（最初の3ページでテキスト抽出を試みる）
    sample_text = ""
    for i, page in enumerate(reader.pages[:3]):
        try:
            sample_text += page.extract_text() or ""
        except:
            pass

    is_scanned = len(sample_text.strip()) < 100
    avg_page_size_mb = file_size_mb / page_count if page_count > 0 else 0

    return {
        "file_path": pdf_path,
        "file_size_mb": round(file_size_mb, 2),
        "page_count": page_count,
        "avg_page_size_mb": round(avg_page_size_mb, 3),
        "is_scanned": is_scanned
    }


def calculate_pages_per_chunk(file_size_mb: float, page_count: int) -> int:
    """最適な分割単位を計算"""
    if page_count == 0:
        return 1

    avg_page_size_mb = file_size_mb / page_count
    if avg_page_size_mb <= 0:
        return MAX_PAGES_PER_CHUNK

    pages_per_chunk = max(1, int(TARGET_CHUNK_SIZE_MB / avg_page_size_mb))
    return min(pages_per_chunk, MAX_PAGES_PER_CHUNK)


def split_pdf(pdf_path: str, output_dir: str, pages_per_chunk: int) -> list:
    """PDFをチャンクに分割"""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    chunks = []
    chunk_num = 1

    for start_page in range(0, total_pages, pages_per_chunk):
        end_page = min(start_page + pages_per_chunk, total_pages)

        writer = PdfWriter()
        for page_idx in range(start_page, end_page):
            writer.add_page(reader.pages[page_idx])

        chunk_filename = f"chunk_{chunk_num:03d}.pdf"
        chunk_path = os.path.join(output_dir, chunk_filename)

        with open(chunk_path, "wb") as f:
            writer.write(f)

        chunks.append({
            "chunk_num": chunk_num,
            "file_path": chunk_path,
            "start_page": start_page + 1,
            "end_page": end_page
        })

        chunk_num += 1

    return chunks


def extract_text_from_pdf(pdf_path: str) -> list:
    """PDFからテキストを抽出（ページごと）"""
    try:
        import pdfplumber
        use_pdfplumber = True
    except ImportError:
        use_pdfplumber = False

    pages = []

    if use_pdfplumber:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    tables = page.extract_tables()

                    # テーブルがあれば整形して追加
                    table_text = ""
                    for table in tables:
                        if table:
                            for row in table:
                                row_text = "\t".join(str(cell) if cell else "" for cell in row)
                                table_text += row_text + "\n"

                    pages.append({
                        "page": i + 1,
                        "text": text,
                        "tables": table_text if table_text else None
                    })
        except Exception as e:
            # pdfplumberで失敗した場合はpypdfにフォールバック
            use_pdfplumber = False

    if not use_pdfplumber:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append({
                "page": i + 1,
                "text": text,
                "tables": None
            })

    return pages


def convert_pdf_to_images(pdf_path: str, output_dir: str, target_size_mb: float = TARGET_IMAGE_SIZE_MB) -> dict:
    """
    PDFを画像に変換（スキャンPDF用）

    各ページをJPEG画像に変換し、目標サイズ以下に圧縮する。
    Claude CodeのReadツールで読み込める形式で出力。
    """
    try:
        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError as e:
        return {
            "success": False,
            "error": f"必要なライブラリがインストールされていません: {e}. pip install pypdfium2 Pillow を実行してください。"
        }

    # ファイル存在チェック
    if not os.path.exists(pdf_path):
        return {
            "success": False,
            "error": f"ファイルが見つかりません: {pdf_path}"
        }

    # 出力ディレクトリ作成
    os.makedirs(output_dir, exist_ok=True)

    try:
        pdf = pdfium.PdfDocument(pdf_path)
        page_count = len(pdf)
        image_files = []

        for i in range(page_count):
            page = pdf[i]

            # 初期解像度（150 DPI相当）
            scale = 2.0  # 72 * 2 = 144 DPI

            # 画像をレンダリング
            bitmap = page.render(scale=scale)
            img = bitmap.to_pil()

            # JPEG形式で保存（品質を調整してサイズを制御）
            page_filename = f"page_{i+1:03d}.jpg"
            page_path = os.path.join(output_dir, page_filename)

            # 品質を調整して目標サイズ以下にする
            quality = 85
            while quality >= 30:
                img.save(page_path, "JPEG", quality=quality, optimize=True)
                file_size_mb = os.path.getsize(page_path) / (1024 * 1024)

                if file_size_mb <= target_size_mb:
                    break
                quality -= 10

            # それでも大きい場合は画像サイズを縮小
            if file_size_mb > target_size_mb:
                # 縮小率を計算
                reduction = (target_size_mb / file_size_mb) ** 0.5
                new_width = int(img.width * reduction)
                new_height = int(img.height * reduction)
                img_resized = img.resize((new_width, new_height), Image.LANCZOS)
                img_resized.save(page_path, "JPEG", quality=70, optimize=True)
                file_size_mb = os.path.getsize(page_path) / (1024 * 1024)

            image_files.append({
                "page": i + 1,
                "file_path": os.path.abspath(page_path),
                "size_mb": round(file_size_mb, 2)
            })

        pdf.close()

        return {
            "success": True,
            "mode": "images",
            "source_pdf": pdf_path,
            "output_dir": os.path.abspath(output_dir),
            "total_pages": page_count,
            "image_files": image_files
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"画像変換エラー: {str(e)}"
        }


def safe_read_pdf(pdf_path: str, threshold_mb: float = DEFAULT_THRESHOLD_MB) -> dict:
    """
    メイン関数: PDFを安全に読み込む

    大きなPDFは自動的に分割して処理し、結果を統合して返す。
    """
    # ファイル存在チェック
    if not os.path.exists(pdf_path):
        return {
            "success": False,
            "error": f"ファイルが見つかりません: {pdf_path}"
        }

    # PDF分析
    analysis = analyze_pdf(pdf_path)
    if "error" in analysis:
        return {
            "success": False,
            "error": analysis["error"]
        }

    file_size_mb = analysis["file_size_mb"]
    page_count = analysis["page_count"]
    is_scanned = analysis["is_scanned"]

    result = {
        "success": True,
        "file_path": pdf_path,
        "file_size_mb": file_size_mb,
        "total_pages": page_count,
        "is_scanned": is_scanned,
        "was_split": False,
        "pages": [],
        "content": ""
    }

    # スキャンPDFの警告
    if is_scanned:
        result["warning"] = "スキャンPDFの可能性があります。テキスト抽出結果が不完全な場合があります。"

    # 分割が必要かどうか判定
    needs_split = file_size_mb > threshold_mb

    if not needs_split:
        # 分割不要: 直接テキスト抽出
        try:
            pages = extract_text_from_pdf(pdf_path)
            result["pages"] = pages
            result["content"] = "\n\n".join(
                f"--- Page {p['page']} ---\n{p['text']}"
                for p in pages
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"テキスト抽出エラー: {str(e)}"
            }
    else:
        # 分割が必要
        result["was_split"] = True
        pages_per_chunk = calculate_pages_per_chunk(file_size_mb, page_count)
        result["pages_per_chunk"] = pages_per_chunk

        # 一時ディレクトリを作成
        temp_dir = tempfile.mkdtemp(prefix="pdf_chunks_")

        try:
            # PDFを分割
            chunks = split_pdf(pdf_path, temp_dir, pages_per_chunk)
            result["chunk_count"] = len(chunks)

            # 各チャンクからテキスト抽出
            all_pages = []
            for chunk in chunks:
                chunk_pages = extract_text_from_pdf(chunk["file_path"])
                # ページ番号を調整
                for i, page in enumerate(chunk_pages):
                    page["page"] = chunk["start_page"] + i
                all_pages.extend(chunk_pages)

            result["pages"] = all_pages
            result["content"] = "\n\n".join(
                f"--- Page {p['page']} ---\n{p['text']}"
                for p in all_pages
            )

        except Exception as e:
            return {
                "success": False,
                "error": f"分割処理エラー: {str(e)}"
            }
        finally:
            # 一時ファイルをクリーンアップ
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

    return result


def main():
    parser = argparse.ArgumentParser(
        description="大容量PDFを自動分割して安全に読み込む"
    )
    parser.add_argument(
        "pdf_path",
        help="読み込むPDFファイルのパス"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD_MB,
        help=f"分割閾値（MB単位、デフォルト: {DEFAULT_THRESHOLD_MB}）"
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="PDFの分析のみ行い、テキスト抽出は行わない"
    )
    parser.add_argument(
        "--to-images",
        action="store_true",
        help="PDFを画像に変換（スキャンPDF用）★推奨"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="画像出力先ディレクトリ（--to-images使用時必須）"
    )
    parser.add_argument(
        "--target-size",
        type=float,
        default=TARGET_IMAGE_SIZE_MB,
        help=f"画像1枚あたりの目標サイズ（MB単位、デフォルト: {TARGET_IMAGE_SIZE_MB}）"
    )

    args = parser.parse_args()

    if args.to_images:
        # 画像変換モード
        if not args.output_dir:
            # デフォルト出力先: PDFと同じフォルダにtemp_imagesを作成
            pdf_dir = os.path.dirname(os.path.abspath(args.pdf_path))
            pdf_name = os.path.splitext(os.path.basename(args.pdf_path))[0]
            args.output_dir = os.path.join(pdf_dir, f"temp_images_{pdf_name}")

        result = convert_pdf_to_images(args.pdf_path, args.output_dir, args.target_size)
    elif args.analyze_only:
        result = analyze_pdf(args.pdf_path)
        result["needs_split"] = result.get("file_size_mb", 0) > args.threshold
        if "file_size_mb" in result and "page_count" in result:
            result["recommended_pages_per_chunk"] = calculate_pages_per_chunk(
                result["file_size_mb"],
                result["page_count"]
            )
    else:
        result = safe_read_pdf(args.pdf_path, args.threshold)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
