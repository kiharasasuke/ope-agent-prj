# 弥生会計 仕訳インポート形式

## ファイル形式要件

- **形式**: CSV (カンマ区切り)
- **文字コード**: Shift-JIS (CP932)
- **改行コード**: CRLF
- **ヘッダー**: 不要（データ行のみ）

## 項目一覧 (全25項目)

| 列 | 項目名 | 必須 | 説明 |
|:---|:-------|:-----|:-----|
| A | 識別フラグ | ○ | 2000: 単一仕訳 |
| B | 伝票No | | 空欄（自動付番） |
| C | 決算 | | 空欄 |
| D | 取引日付 | ○ | YYYY/MM/DD形式 |
| E | 借方勘定科目 | ○ | 勘定科目名 |
| F | 借方補助科目 | | 補助科目名 |
| G | 借方部門 | | 空欄 |
| H | 借方税区分 | ○ | 対象外、課税売上10%など |
| I | 借方金額 | ○ | 整数 |
| J | 借方税金額 | | 空欄 |
| K | 貸方勘定科目 | ○ | 勘定科目名 |
| L | 貸方補助科目 | | 補助科目名 |
| M | 貸方部門 | | 空欄 |
| N | 貸方税区分 | ○ | 対象外、課税売上10%など |
| O | 貸方金額 | ○ | 整数 |
| P | 貸方税金額 | | 空欄 |
| Q | 摘要 | | 取引内容 |
| R | 備考 | | 空欄 |
| S | 伝票番号自動設定 | | 空欄 |
| T | 伝票種別 | | 0 |
| U | 税計算区分 | | 空欄 |
| V | 税額計算対象 | | 空欄 |
| W | 請求書区分 | | 空欄 |
| X | 仕入税額控除 | | 空欄 |
| Y | 定型 | | 0 |

## 出力例

```csv
2000,,,2025/11/04,普通預金,呑家,,対象外,71770,,現金,,,対象外,71770,,AD,,,0,,,,,0
```

## 注意事項

- 金額はカンマなしの整数
- 空欄項目もカンマは必要（例: `,,`）
- 項目内にカンマがある場合はダブルクォートで囲む

## Python出力時の注意（CRLF改行）

弥生会計はCRLF改行が必須（CRのみだとインポート不可）。
Shift-JIS + CRLF で出力する際、`csv.writer` の使い方に注意が必要。

**NG例（空行が入る）**:
```python
# newline='\r\n' と csv.writer の組み合わせは二重改行になる
# csv.writerが内部で改行を追加 → \r\n + \r\n = 空行
with open(output_file, 'w', encoding='cp932', newline='\r\n') as f:
    writer = csv.writer(f)
```

**OK例1: csv.writer + lineterminator**:
```python
# newline='' で自動改行変換を無効化し、lineterminatorでCRLFを指定
with open(output_file, 'w', encoding='cp932', newline='') as f:
    writer = csv.writer(f, lineterminator='\r\n')
    for row in rows:
        writer.writerow(row)
```

**OK例2: バイナリモードで直接書き込む**:
```python
with open(output_file, 'wb') as f:
    for row in rows:
        line = ','.join(row) + '\r\n'
        f.write(line.encode('cp932'))
