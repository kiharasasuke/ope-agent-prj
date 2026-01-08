---
name: pdf-chunked-reader
description: |
  大容量PDFを自動分割して読み込むユーティリティスキル。Claude CodeのAPI制限（約5-10MB）を回避する。
  他のスキルからPDFを読み込む際に使用。413エラーが発生した場合や、3MB以上のPDFを処理する際に自動的に分割処理を行う。
---

# PDF自動分割読み込みスキル

Claude CodeのAPI制限を回避するため、大きなPDFファイルを自動的に分割して読み込むユーティリティ。

## 使用方法

### 画像変換モード（スキャンPDF用）★推奨

銀行明細などのスキャンPDFを処理する場合は、必ずこのモードを使用。

```bash
python .claude/skills/pdf-chunked-reader/scripts/safe_read_pdf.py "path/to/file.pdf" --to-images --output-dir ./temp_images
```

**出力例:**
```json
{
  "success": true,
  "mode": "images",
  "source_pdf": "path/to/file.pdf",
  "output_dir": "C:/absolute/path/to/temp_images",
  "total_pages": 3,
  "image_files": [
    {"page": 1, "file_path": "C:/absolute/path/to/temp_images/page_001.jpg", "size_mb": 1.5},
    {"page": 2, "file_path": "C:/absolute/path/to/temp_images/page_002.jpg", "size_mb": 1.8},
    {"page": 3, "file_path": "C:/absolute/path/to/temp_images/page_003.jpg", "size_mb": 1.2}
  ]
}
```

**その後の処理:**
出力されたJSONの `image_files` の各 `file_path` をReadツールで順番に読み込む。

### テキスト抽出モード（テキストベースPDF用）

テキストが埋め込まれたPDF（スキャンではないPDF）の場合:

```bash
python .claude/skills/pdf-chunked-reader/scripts/safe_read_pdf.py "path/to/file.pdf"
```

### 分析モード

PDFの情報を確認するだけ（変換なし）:

```bash
python .claude/skills/pdf-chunked-reader/scripts/safe_read_pdf.py "file.pdf" --analyze-only
```

## 他スキルからの利用（重要）

### スキャンPDFを読み込む場合

PDFを読み込む必要があるスキルでは、以下の手順を実行:

**Step 1: PDFを画像に変換**
```bash
python .claude/skills/pdf-chunked-reader/scripts/safe_read_pdf.py "path/to/file.pdf" --to-images --output-dir ./temp/images
```

**Step 2: JSONからimage_filesを取得**

出力されたJSONの `image_files` 配列から各画像のパスを取得。

**Step 3: 各画像をReadツールで読み込み**

```
Read(./temp/images/page_001.jpg)
Read(./temp/images/page_002.jpg)
Read(./temp/images/page_003.jpg)
```

**Step 4: 処理完了後、一時画像を削除（オプション）**

## オプション一覧

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--to-images` | 画像変換モード（スキャンPDF用） | - |
| `--output-dir` | 画像出力先ディレクトリ | PDFと同じ場所 |
| `--target-size` | 画像1枚の目標サイズ（MB） | 2.0 |
| `--threshold` | テキストモードの分割閾値（MB） | 3.0 |
| `--analyze-only` | 分析のみ実行 | - |

## サイズ閾値

| 項目 | 値 |
|------|-----|
| 画像目標サイズ | 2MB/枚 |
| テキストモード分割閾値 | 3MB |
| 目標チャンクサイズ | 2MB |

## 必要ライブラリ

```bash
pip install pypdf pdfplumber pypdfium2 Pillow
```

- `pypdfium2`: PDF→画像変換
- `Pillow`: 画像処理・圧縮
- `pypdf`: PDF分割
- `pdfplumber`: テーブル抽出

## エラーハンドリング

| エラー | 対処 |
|--------|------|
| `success: false` | errorフィールドを確認 |
| 413エラー | `--to-images`モードを使用 |
| 画像が大きすぎる | `--target-size 1.5` で目標サイズを下げる |
| ライブラリ未インストール | `pip install pypdfium2 Pillow` を実行 |
