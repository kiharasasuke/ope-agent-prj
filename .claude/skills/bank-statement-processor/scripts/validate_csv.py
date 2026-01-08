#!/usr/bin/env python3
"""
銀行取引明細CSVの整合性検証スクリプト

使用方法:
    python validate_csv.py <csv_file>
    python validate_csv.py --fix <csv_file>  # 自動修正モード
    python validate_csv.py --check-order <csv_file> <image_order_file>  # 順序検証モード

出力形式:
    日付,摘要,出金額,入金額,残高
"""

import csv
import sys
import argparse
import json
from datetime import datetime
from pathlib import Path


def parse_date(date_str: str) -> datetime | None:
    """日付文字列をパース（元号対応）"""
    date_str = date_str.strip()

    # 元号変換
    era_map = {
        'R': 2018,  # 令和1年 = 2019年
        'H': 1988,  # 平成1年 = 1989年
        'S': 1925,  # 昭和1年 = 1926年
    }

    for era, base_year in era_map.items():
        if date_str.startswith(era):
            try:
                # R6.1.15 形式
                parts = date_str[1:].split('.')
                if len(parts) == 3:
                    year = base_year + int(parts[0])
                    month = int(parts[1])
                    day = int(parts[2])
                    return datetime(year, month, day)
            except (ValueError, IndexError):
                pass

    # 標準形式を試行
    formats = [
        '%Y/%m/%d',
        '%Y-%m-%d',
        '%Y.%m.%d',
        '%Y年%m月%d日',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


def parse_amount(amount_str: str) -> int:
    """金額文字列を整数にパース"""
    if not amount_str or amount_str.strip() == '':
        return 0

    # カンマ・スペース除去
    amount_str = amount_str.replace(',', '').replace(' ', '').strip()

    try:
        return int(amount_str)
    except ValueError:
        return 0


def validate_row(row: dict, prev_balance: int | None) -> tuple[bool, str, int | None]:
    """
    行の整合性を検証

    Returns:
        (is_valid, error_message, calculated_balance)
    """
    try:
        deposit = parse_amount(row.get('入金額', '0'))
        withdrawal = parse_amount(row.get('出金額', '0'))
        balance = parse_amount(row.get('残高', '0'))
    except Exception as e:
        return False, f"金額パースエラー: {e}", None

    errors = []

    # 入金額 >= 0
    if deposit < 0:
        errors.append(f"入金額が負: {deposit}")

    # 出金額 >= 0
    if withdrawal < 0:
        errors.append(f"出金額が負: {withdrawal}")

    # 入金と出金が同時に0以外は禁止
    if deposit > 0 and withdrawal > 0:
        errors.append(f"入出金同時発生: 入金={deposit}, 出金={withdrawal}")

    # 残高計算チェック
    if prev_balance is not None:
        expected_balance = prev_balance + deposit - withdrawal
        if expected_balance != balance:
            errors.append(f"残高不整合: 期待値={expected_balance}, 実際={balance}")

    # 残高 >= 0（当座除く - 摘要で判定）
    description = row.get('摘要', '')
    if balance < 0 and '当座' not in description:
        errors.append(f"残高がマイナス: {balance}")

    if errors:
        return False, '; '.join(errors), balance

    return True, '', balance


def try_fix_amount(prev_balance: int, deposit: int, withdrawal: int, balance: int) -> tuple[int, int, str] | None:
    """
    1桁のOCR誤読を修正

    Returns:
        (fixed_deposit, fixed_withdrawal, fix_description) or None
    """
    expected = prev_balance + deposit - withdrawal
    diff = balance - expected

    if diff == 0:
        return None  # 修正不要

    # 入金額の1桁修正を試行
    if withdrawal == 0:
        fixed_deposit = deposit + diff
        if fixed_deposit >= 0:
            # 1桁置換で済むかチェック
            deposit_str = str(deposit)
            fixed_str = str(fixed_deposit)
            if len(deposit_str) == len(fixed_str):
                changes = sum(1 for a, b in zip(deposit_str, fixed_str) if a != b)
                if changes == 1:
                    return fixed_deposit, withdrawal, f"入金額修正: {deposit} -> {fixed_deposit}"

    # 出金額の1桁修正を試行
    if deposit == 0:
        fixed_withdrawal = withdrawal - diff
        if fixed_withdrawal >= 0:
            withdrawal_str = str(withdrawal)
            fixed_str = str(fixed_withdrawal)
            if len(withdrawal_str) == len(fixed_str):
                changes = sum(1 for a, b in zip(withdrawal_str, fixed_str) if a != b)
                if changes == 1:
                    return deposit, fixed_withdrawal, f"出金額修正: {withdrawal} -> {fixed_withdrawal}"

    return None


def validate_csv(file_path: str, fix_mode: bool = False) -> tuple[bool, list[str], list[dict]]:
    """
    CSVファイル全体を検証

    Returns:
        (all_valid, error_messages, fixed_rows)
    """
    errors = []
    fixed_rows = []
    prev_balance = None
    prev_date = None

    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader, start=2):  # ヘッダー行を1とする
            # 日付チェック
            date = parse_date(row.get('日付', ''))
            if date and prev_date and date < prev_date:
                errors.append(f"行{i}: 日付逆行 ({row.get('日付')})")
            prev_date = date

            # 整合性チェック
            is_valid, error_msg, balance = validate_row(row, prev_balance)

            if not is_valid:
                if fix_mode and prev_balance is not None:
                    # 修正を試行
                    deposit = parse_amount(row.get('入金額', '0'))
                    withdrawal = parse_amount(row.get('出金額', '0'))
                    current_balance = parse_amount(row.get('残高', '0'))

                    fix_result = try_fix_amount(prev_balance, deposit, withdrawal, current_balance)
                    if fix_result:
                        fixed_deposit, fixed_withdrawal, fix_desc = fix_result
                        row['入金額'] = str(fixed_deposit)
                        row['出金額'] = str(fixed_withdrawal)
                        errors.append(f"行{i}: {fix_desc}")
                        balance = current_balance
                    else:
                        errors.append(f"行{i}: {error_msg} (自動修正不可)")
                else:
                    errors.append(f"行{i}: {error_msg}")

            fixed_rows.append(row)
            prev_balance = balance

    all_valid = len([e for e in errors if '自動修正不可' in e or '逆行' in e]) == 0
    return all_valid, errors, fixed_rows


def validate_order_with_reference(csv_path: str, reference_path: str) -> tuple[bool, list[str]]:
    """
    CSVの順序が参照ファイル（画像から抽出した順序）と一致するか検証

    reference_path: JSONファイルまたはテキストファイル
    JSON形式: [{"日付": "2025/11/04", "摘要": "AD", "金額": 71770}, ...]
    テキスト形式: 1行1取引で「日付,摘要,金額」

    Returns:
        (is_valid, error_messages)
    """
    errors = []

    # CSVを読み込み
    csv_rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            deposit = parse_amount(row.get('入金額', '0'))
            withdrawal = parse_amount(row.get('出金額', '0'))
            amount = deposit if deposit > 0 else withdrawal
            csv_rows.append({
                '日付': row.get('日付', '').strip(),
                '摘要': row.get('摘要', '').strip(),
                '金額': amount,
            })

    # 参照ファイルを読み込み
    ref_rows = []
    ref_path = Path(reference_path)

    if ref_path.suffix == '.json':
        with open(reference_path, 'r', encoding='utf-8') as f:
            ref_data = json.load(f)
            for item in ref_data:
                ref_rows.append({
                    '日付': str(item.get('日付', '')).strip(),
                    '摘要': str(item.get('摘要', '')).strip(),
                    '金額': int(item.get('金額', 0)),
                })
    else:
        # テキスト形式（日付,摘要,金額）
        with open(reference_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',')
                if len(parts) >= 3:
                    ref_rows.append({
                        '日付': parts[0].strip(),
                        '摘要': parts[1].strip(),
                        '金額': int(parts[2].strip()),
                    })

    # 行数チェック
    if len(csv_rows) != len(ref_rows):
        errors.append(f"行数不一致: CSV={len(csv_rows)}行, 参照={len(ref_rows)}行")

    # 順序チェック
    min_len = min(len(csv_rows), len(ref_rows))
    for i in range(min_len):
        csv_row = csv_rows[i]
        ref_row = ref_rows[i]

        mismatches = []

        if csv_row['日付'] != ref_row['日付']:
            mismatches.append(f"日付: CSV={csv_row['日付']}, 参照={ref_row['日付']}")

        if csv_row['金額'] != ref_row['金額']:
            mismatches.append(f"金額: CSV={csv_row['金額']}, 参照={ref_row['金額']}")

        # 摘要は部分一致でチェック（OCR誤差を考慮）
        if ref_row['摘要'] and ref_row['摘要'] not in csv_row['摘要'] and csv_row['摘要'] not in ref_row['摘要']:
            mismatches.append(f"摘要: CSV={csv_row['摘要']}, 参照={ref_row['摘要']}")

        if mismatches:
            errors.append(f"行{i+2}: 順序不一致 - {'; '.join(mismatches)}")

    is_valid = len(errors) == 0
    return is_valid, errors


def validate_balance_order(csv_path: str) -> tuple[bool, list[str]]:
    """
    残高の連続性から順序が正しいか検証

    残高計算が成立する = 順序が正しい
    残高計算が成立しない = 順序が間違っている可能性

    Returns:
        (is_valid, error_messages)
    """
    errors = []
    prev_balance = None

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader, start=2):
            deposit = parse_amount(row.get('入金額', '0'))
            withdrawal = parse_amount(row.get('出金額', '0'))
            balance = parse_amount(row.get('残高', '0'))

            if prev_balance is not None:
                expected = prev_balance + deposit - withdrawal
                if expected != balance:
                    errors.append(
                        f"行{i}: 残高不整合（順序エラーの可能性）- "
                        f"前残高={prev_balance}, 入金={deposit}, 出金={withdrawal}, "
                        f"期待残高={expected}, 実際残高={balance}"
                    )

            prev_balance = balance

    is_valid = len(errors) == 0
    return is_valid, errors


def main():
    parser = argparse.ArgumentParser(description='銀行取引明細CSVの整合性検証')
    parser.add_argument('csv_file', help='検証するCSVファイル')
    parser.add_argument('--fix', action='store_true', help='自動修正モード')
    parser.add_argument('--output', '-o', help='修正後の出力ファイル')
    parser.add_argument('--check-order', metavar='REF_FILE',
                        help='順序検証モード: 参照ファイル（JSON/TXT）と比較')
    parser.add_argument('--strict-order', action='store_true',
                        help='厳密順序検証: 残高計算で順序の正しさを検証')

    args = parser.parse_args()

    if not Path(args.csv_file).exists():
        print(f"エラー: ファイルが見つかりません: {args.csv_file}")
        sys.exit(1)

    all_valid = True

    # 基本検証
    is_valid, errors, fixed_rows = validate_csv(args.csv_file, fix_mode=args.fix)
    if errors:
        print("=== 基本検証結果 ===")
        for error in errors:
            print(f"  {error}")
        if not is_valid:
            all_valid = False
    else:
        print("基本検証OK: すべての行が整合しています")

    # 順序検証（参照ファイルとの比較）
    if args.check_order:
        if not Path(args.check_order).exists():
            print(f"エラー: 参照ファイルが見つかりません: {args.check_order}")
            sys.exit(1)

        order_valid, order_errors = validate_order_with_reference(args.csv_file, args.check_order)
        print("\n=== 順序検証結果（参照ファイル比較） ===")
        if order_errors:
            for error in order_errors:
                print(f"  {error}")
            all_valid = False
        else:
            print("順序検証OK: 参照ファイルと一致しています")

    # 厳密順序検証（残高計算ベース）
    if args.strict_order:
        balance_valid, balance_errors = validate_balance_order(args.csv_file)
        print("\n=== 厳密順序検証結果（残高計算） ===")
        if balance_errors:
            for error in balance_errors:
                print(f"  {error}")
            print("\n【重要】残高不整合は順序が画像と異なっている可能性があります")
            print("画像の順序を再確認し、CSVを修正してください")
            all_valid = False
        else:
            print("順序検証OK: 残高計算が全行で成立しています")

    # 修正出力
    if args.fix and args.output:
        with open(args.output, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['日付', '摘要', '出金額', '入金額', '残高']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(fixed_rows)
        print(f"\n修正済みCSVを出力: {args.output}")

    print(f"\n最終結果: {'OK' if all_valid else 'NG'}")
    sys.exit(0 if all_valid else 1)


if __name__ == '__main__':
    main()
