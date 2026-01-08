---
name: bank-to-yayoi
description: |
  銀行取引明細CSVを弥生会計の仕訳インポート形式(25項目CSV)に変換するスキル。
  月次経理処理で複数店舗のデータを一括処理できる。
  使用タイミング: (1) 銀行明細CSVを弥生会計にインポートしたい時 (2) 「弥生会計」「仕訳」「インポート」「変換」などのキーワードが含まれる時 (3) 月次経理処理の一環として銀行データを処理する時
---

# bank-to-yayoi

銀行取引明細CSV → 弥生会計仕訳インポート形式への変換スキル。

## クイックスタート

```bash
python scripts/convert_to_yayoi.py <入力CSVフォルダ> <出力ファイル>
```

例:
```bash
python scripts/convert_to_yayoi.py ./output/01_預金 ./output/yayoi/all_yayoi.csv
```

複数店舗のCSVを1つのファイルに統合して出力する。

## 入力形式

```csv
日付,摘要,出金額,入金額,残高
2025/11/04,AD,0,71770,1917590
```

## 出力形式

弥生会計仕訳インポート形式（25項目、Shift-JIS、CRLF）

## マッピングルール

詳細は [references/mapping.md](references/mapping.md) を参照。

| 摘要パターン | 借方 | 貸方 |
|-------------|------|------|
| AD、ATM入金 | 普通預金(店舗名) | 現金 |
| ATM出金 | 小口現金(店舗名) | 普通預金(店舗名) |
| ｱｵｷﾞﾘｺｰﾎﾟﾚ含む | 普通預金(資金移動) | 普通預金(店舗名) |

## 弥生会計形式仕様

詳細は [references/yayoi_format.md](references/yayoi_format.md) を参照。
