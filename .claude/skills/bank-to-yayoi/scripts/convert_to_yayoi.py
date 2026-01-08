#!/usr/bin/env python3
"""
銀行取引明細CSV → 弥生会計仕訳インポート形式 変換スクリプト
"""

import csv
import os
import sys
from pathlib import Path


def extract_store_name(filename: str) -> str:
    """ファイル名から店舗名を抽出"""
    # 例: 呑家_普通預金_202511-202512.csv → 呑家
    return filename.split("_")[0]


# 店舗マッピング定義
STORE_MAPPING = {
    "呑家": {
        "普通預金の補助科目": "さわやか/呑家/1106478",
        "現金の補助科目": "呑家",
    },
    "西口アオギリ": {
        "普通預金の補助科目": "さわやか/西口ｱｵｷﾞﾘ",
        "現金の補助科目": "西口アオギリ",
    },
    "ホドケバ": {
        "普通預金の補助科目": "さわやか/ﾎﾄﾞｹﾊﾞ/1119209",
        "現金の補助科目": "ホドケバ",
    },
    "はんろく": {
        "普通預金の補助科目": "三井住友/はんろく",
        "現金の補助科目": "はんろく",
    },
    "警視鳥": {
        "普通預金の補助科目": "さわやか/警視鳥",
        "現金の補助科目": "警視鳥",
    },
}


def get_store_sub_accounts(store: str) -> dict:
    """店舗名から補助科目を取得"""
    if store in STORE_MAPPING:
        return STORE_MAPPING[store]
    # マッピングがない場合は店舗名をそのまま使用
    return {
        "普通預金の補助科目": store,
        "現金の補助科目": store,
    }


def get_journal_entry(tekiyo: str, store: str, amount: int, is_deposit: bool) -> dict:
    """摘要から仕訳を決定

    基本ルール：
    - 入金（is_deposit=True）→ 普通預金が借方
    - 出金（is_deposit=False）→ 普通預金が貸方
    """

    # 店舗の補助科目を取得
    sub_accounts = get_store_sub_accounts(store)
    deposit_sub = sub_accounts["普通預金の補助科目"]
    cash_sub = sub_accounts["現金の補助科目"]

    # === 出金パターン（普通預金が貸方） ===
    if not is_deposit:
        # 資金移動（アオギリコーポレーション宛）
        if "ｱｵｷﾞﾘｺｰﾎﾟﾚ" in tekiyo or "アオギリコーポレ" in tekiyo:
            return {
                "debit_account": "普通預金",
                "debit_sub": "資金移動",
                "credit_account": "普通預金",
                "credit_sub": deposit_sub,
                "tax": "対象外",
            }

        # ATM出金・カード（現金引出）
        if tekiyo in ("ATM出金", "カード", "CD"):
            return {
                "debit_account": "小口現金",
                "debit_sub": cash_sub,
                "credit_account": "普通預金",
                "credit_sub": deposit_sub,
                "tax": "対象外",
            }

        # 手数料（カード手数料、振込手数料）
        if "手数料" in tekiyo:
            return {
                "debit_account": "支払手数料",
                "debit_sub": "",
                "credit_account": "普通預金",
                "credit_sub": deposit_sub,
                "tax": "対象外",
            }

        # その他の出金（デフォルト: 小口現金への出金）
        return {
            "debit_account": "小口現金",
            "debit_sub": cash_sub,
            "credit_account": "普通預金",
            "credit_sub": deposit_sub,
            "tax": "対象外",
        }

    # === 入金パターン（普通預金が借方） ===
    # AD、ATM入金、現金などの入金
    return {
        "debit_account": "普通預金",
        "debit_sub": deposit_sub,
        "credit_account": "現金",
        "credit_sub": cash_sub,
        "tax": "対象外",
    }


def convert_row_to_yayoi(date: str, tekiyo: str, withdrawal: int, deposit: int, store: str) -> str:
    """1行を弥生会計形式に変換"""

    # 金額を決定
    if deposit > 0:
        amount = deposit
        is_deposit = True
    else:
        amount = withdrawal
        is_deposit = False

    # 仕訳を取得
    entry = get_journal_entry(tekiyo, store, amount, is_deposit)

    # 弥生会計形式の25項目を構築
    columns = [
        "2000",                      # A: 識別フラグ
        "",                          # B: 伝票No
        "",                          # C: 決算
        date,                        # D: 取引日付
        entry["debit_account"],      # E: 借方勘定科目
        entry["debit_sub"],          # F: 借方補助科目
        "",                          # G: 借方部門
        entry["tax"],                # H: 借方税区分
        str(amount),                 # I: 借方金額
        "",                          # J: 借方税金額
        entry["credit_account"],     # K: 貸方勘定科目
        entry["credit_sub"],         # L: 貸方補助科目
        "",                          # M: 貸方部門
        entry["tax"],                # N: 貸方税区分
        str(amount),                 # O: 貸方金額
        "",                          # P: 貸方税金額
        tekiyo,                      # Q: 摘要
        "",                          # R: 備考
        "",                          # S: 伝票番号自動設定
        "0",                         # T: 伝票種別
        "",                          # U: 税計算区分
        "",                          # V: 税額計算対象
        "",                          # W: 請求書区分
        "",                          # X: 仕入税額控除
        "0",                         # Y: 定型
    ]

    return ",".join(columns)


def convert_file_to_lines(input_path: Path) -> list:
    """CSVファイルを変換して行リストを返す"""

    store = extract_store_name(input_path.name)
    print(f"Processing: {input_path.name} (store: {store})")

    output_lines = []

    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row["日付"]
            tekiyo = row["摘要"]
            withdrawal = int(row["出金額"]) if row["出金額"] else 0
            deposit = int(row["入金額"]) if row["入金額"] else 0

            # 入出金が0の行はスキップ
            if withdrawal == 0 and deposit == 0:
                continue

            yayoi_line = convert_row_to_yayoi(date, tekiyo, withdrawal, deposit, store)
            output_lines.append(yayoi_line)

    print(f"  -> {len(output_lines)} rows")
    return output_lines


def main():
    if len(sys.argv) < 3:
        print("Usage: python convert_to_yayoi.py <input_folder> <output_file>")
        print("Example: python convert_to_yayoi.py ./output/01_預金 ./output/yayoi/all_yayoi.csv")
        sys.exit(1)

    input_folder = Path(sys.argv[1])
    output_file = Path(sys.argv[2])

    if not input_folder.exists():
        print(f"Error: Input folder not found: {input_folder}")
        sys.exit(1)

    output_file.parent.mkdir(parents=True, exist_ok=True)

    # CSVファイルを処理
    csv_files = list(input_folder.glob("*.csv"))
    if not csv_files:
        print(f"Error: No CSV files found in {input_folder}")
        sys.exit(1)

    # 全ファイルを1つに統合
    all_lines = []
    for csv_file in sorted(csv_files):
        all_lines.extend(convert_file_to_lines(csv_file))

    # Shift-JIS, CRLF で1ファイルに出力
    with open(output_file, "w", encoding="cp932", newline="") as f:
        f.write("\r\n".join(all_lines))
        f.write("\r\n")

    print(f"\nOutput: {output_file}")
    print(f"Completed: {len(csv_files)} files -> {len(all_lines)} total rows")


if __name__ == "__main__":
    main()
