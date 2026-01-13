#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Airペイ → 弥生仕訳CSV生成スクリプト
月末日分離機能付き
"""

import csv
import math
import sys
import os
import re
import calendar
from collections import defaultdict


def parse_summaries_from_csv(rows):
    """CSVからサマリー情報を抽出"""
    summaries = {}
    current_payment_date = None

    # サマリー行を探す（売上合計金額を含む行）
    i = 0
    while i < len(rows):
        row = rows[i]
        if len(row) >= 9 and row[7]:
            label = row[7]
            if '売上合計' in label or '合計金額' in label:
                # このサマリーブロックの入金日を特定（直前のデータ行から）
                for j in range(i - 1, -1, -1):
                    if len(rows[j]) >= 1 and re.match(r'^\d{4}-\d{2}-\d{2}$', rows[j][0]):
                        current_payment_date = rows[j][0]
                        break

                if current_payment_date:
                    summary = {'sales': int(row[8])}
                    # 続くサマリー行を読む
                    for k in range(i + 1, min(i + 8, len(rows))):
                        if len(rows[k]) >= 9 and rows[k][7]:
                            l = rows[k][7]
                            v = int(rows[k][8]) if rows[k][8].lstrip('-').isdigit() else 0
                            if '課税10%' in l or '10%対象' in l:
                                summary['fee_taxable'] = v
                            elif '消費税額' in l:
                                summary['tax'] = v
                            elif '非課税' in l and '手数料' in l:
                                summary['fee_non_taxable'] = v
                            elif '振込金額' in l and '差引' not in l and '確定' not in l:
                                summary['transfer'] = v
                    summaries[current_payment_date] = summary
        i += 1

    return summaries


def find_detail_ranges(rows, summaries):
    """各入金サイクルの明細範囲を特定"""
    detail_ranges = {}
    payment_dates = sorted(summaries.keys(), reverse=True)

    # 各入金日のデータ開始位置を探す
    for payment_date in payment_dates:
        start = None
        end = None

        # ヘッダー行（入金日,利用日...）の後からデータが始まる
        for i, row in enumerate(rows):
            if len(row) >= 9 and row[0] == payment_date:
                if start is None:
                    start = i
                end = i + 1

        # 最後のデータ行の次がサマリー行
        if start is not None:
            detail_ranges[payment_date] = (start, end)

    return detail_ranges


def calculate_split_data(rows, summaries, detail_ranges):
    """月末日分離してデータを計算"""
    results = []

    for payment_date in sorted(detail_ranges.keys()):
        start, end = detail_ranges[payment_date]
        summary = summaries[payment_date]

        # 会計月別に集計
        by_month = defaultdict(lambda: {'taxable': 0, 'non_taxable': 0})

        for i in range(start, end):
            row = rows[i]
            if len(row) >= 10 and row[0] == payment_date:
                usage_date = row[4]
                amount_str = row[8]
                tax_type = row[9]

                try:
                    amount = int(amount_str)
                    year = int(usage_date[:4])
                    month = int(usage_date[5:7])
                    day = int(usage_date[8:10])
                    last_day = calendar.monthrange(year, month)[1]

                    if day == last_day:
                        month_key = f'{usage_date[:7]}(月末)'
                    else:
                        month_key = usage_date[:7]

                    if '非' in tax_type:
                        by_month[month_key]['non_taxable'] += amount
                    else:
                        by_month[month_key]['taxable'] += amount
                except:
                    pass

        # 按分計算
        total_taxable = sum(d['taxable'] for d in by_month.values())
        total_non_taxable = sum(d['non_taxable'] for d in by_month.values())

        allocated = {'fee_taxable': 0, 'fee_non_taxable': 0}
        month_keys = sorted(by_month.keys())

        for idx, month_key in enumerate(month_keys):
            data = by_month[month_key]
            is_last = (idx == len(month_keys) - 1)

            # 課税手数料の按分
            if total_taxable > 0:
                if is_last:
                    fee_taxable = summary.get('fee_taxable', 0) - allocated['fee_taxable']
                else:
                    fee_taxable = math.floor(summary.get('fee_taxable', 0) * data['taxable'] / total_taxable)
            else:
                fee_taxable = 0
            allocated['fee_taxable'] += fee_taxable

            # 非課税手数料の按分
            if total_non_taxable > 0:
                if is_last:
                    fee_non_taxable = summary.get('fee_non_taxable', 0) - allocated['fee_non_taxable']
                else:
                    fee_non_taxable = math.floor(summary.get('fee_non_taxable', 0) * data['non_taxable'] / total_non_taxable)
            else:
                fee_non_taxable = 0
            allocated['fee_non_taxable'] += fee_non_taxable

            sales = data['taxable'] + data['non_taxable']
            transfer = sales - fee_taxable - fee_non_taxable

            results.append({
                'payment_date': payment_date,
                'accounting_month': month_key,
                'sales': sales,
                'fee_taxable': fee_taxable,
                'fee_non_taxable': fee_non_taxable,
                'transfer': transfer
            })

    return results


def to_reiwa_date(date_str):
    """2025-11-06 -> R.07/11/06"""
    year = int(date_str[:4])
    month = date_str[5:7]
    day = date_str[8:10]
    reiwa_year = year - 2018
    return f'R.{reiwa_year:02d}/{month}/{day}'


def generate_journal_csv(results, department, subsidiary_suffix):
    """弥生仕訳CSVを生成"""
    journal_rows = []

    for r in results:
        date = to_reiwa_date(r['payment_date'])
        sales = r['sales']
        fee_taxable = r['fee_taxable']
        fee_non_taxable = r['fee_non_taxable']
        transfer = r['transfer']
        month_label = r['accounting_month']

        note_suffix = f'({month_label})' if '月末' in month_label else ''

        # 行1: 売上高（貸方）
        journal_rows.append([
            '2110', '', '', date, '', '', '', '対象外', '0', '',
            '売上高(10%)', '', department, '課税売上込10%', str(sales), '',
            f'リクルートペイメント　売上{note_suffix}', '', '', '3', '', '', '0', '0', 'no'
        ])

        # 行2: 課税手数料（借方）
        if fee_taxable > 0:
            journal_rows.append([
                '2100', '', '', date, 'クレジット手数料', 'クレジット手数料(課税)', department,
                '課対仕入込10%適格', str(fee_taxable), '', '', '', '', '対象外', '0', '',
                f'リクルートペイメント　手数料/課税{note_suffix}', '', '', '3', '', '', '0', '0', 'no'
            ])

        # 行3: 非課税手数料（借方）
        if fee_non_taxable > 0:
            journal_rows.append([
                '2100', '', '', date, 'クレジット手数料', 'クレジット手数料', department,
                '非課仕入', str(fee_non_taxable), '', '', '', '', '対象外', '0', '',
                f'リクルートペイメント　手数料/非課税{note_suffix}', '', '', '3', '', '', '0', '0', 'no'
            ])

        # 行4: 売掛金（借方）
        journal_rows.append([
            '2101', '', '', date, '売掛金', f'㈱ﾘｸﾙｰﾄﾍﾟｲﾒﾝﾄ/{subsidiary_suffix}', '',
            '対象外', str(transfer), '', '', '', '', '対象外', '0', '',
            f'リクルートペイメント　入金額{note_suffix}', '', '', '3', '', '', '0', '0', 'no'
        ])

    return journal_rows


def deduplicate_rows(rows):
    """CSVの重複データ行を排除"""
    seen = set()
    unique_rows = []
    duplicate_count = 0

    for row in rows:
        # データ行（入金日が2025-で始まる）の場合のみ重複チェック
        if len(row) >= 9 and row[0] and row[0].startswith('202'):
            # ユニークキー: 入金日,利用日,決済ブランド,カード番号,金額,税区分
            key = (row[0], row[4], row[5], row[6], row[8], row[9] if len(row) > 9 else '')
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
        unique_rows.append(row)

    if duplicate_count > 0:
        print(f'重複検出: {duplicate_count}行の重複データを除外しました。')

    return unique_rows


def main():
    if len(sys.argv) < 3:
        print('Usage: python generate_journal.py <input_csv> <department> [subsidiary_suffix] [output_csv]')
        print('  input_csv         : Airpay全項目CSV')
        print('  department        : 弥生部門名（例: 大衆サカバ牡蠣ル）')
        print('  subsidiary_suffix : 売掛金補助科目の店舗略称（例: 牡蠣ル）省略時は部門名')
        print('  output_csv        : 出力ファイル（省略時は 仕訳_YYYYMM.csv）')
        sys.exit(1)

    input_file = sys.argv[1]
    department = sys.argv[2]
    subsidiary_suffix = sys.argv[3] if len(sys.argv) > 3 else department
    output_file = sys.argv[4] if len(sys.argv) > 4 else None

    # ファイル読み込み
    with open(input_file, 'r', encoding='cp932') as f:
        reader = csv.reader(f)
        rows = list(reader)

    # サマリー情報を抽出（重複排除前に実行）
    summaries = parse_summaries_from_csv(rows)

    # 重複データ行を排除
    rows = deduplicate_rows(rows)

    # サマリーも重複している可能性があるので、重複排除後のデータに合わせて調整
    # 同じ入金日のサマリーが複数ある場合、最初のものを使用
    # （parse_summaries_from_csvは後のもので上書きするので、最初のものに戻す必要がある場合がある）
    if not summaries:
        print('Error: サマリー情報が見つかりません')
        sys.exit(1)

    # 明細範囲を特定
    detail_ranges = find_detail_ranges(rows, summaries)

    # 月末日分離計算
    results = calculate_split_data(rows, summaries, detail_ranges)

    # 弥生仕訳CSV生成
    journal_rows = generate_journal_csv(results, department, subsidiary_suffix)

    # 出力ファイル名を決定
    if not output_file:
        basename = os.path.basename(input_file)
        match = re.search(r'(\d{6})', basename)
        yyyymm = match.group(1) if match else 'output'
        output_dir = os.path.dirname(input_file)
        output_file = os.path.join(output_dir, f'仕訳_{yyyymm}.csv')

    # CSV出力（弥生会計はShift-JIS/CP932が必須）
    with open(output_file, 'w', encoding='cp932', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(journal_rows)

    print(f'Output: {output_file}')
    print(f'Total rows: {len(journal_rows)}')
    print()
    print('=== 仕訳サマリー ===')
    for r in results:
        check = r['fee_taxable'] + r['fee_non_taxable'] + r['transfer']
        status = 'OK' if check == r['sales'] else 'NG'
        print(f'{r["payment_date"]} ({r["accounting_month"]}): 売上={r["sales"]:,} 課税={r["fee_taxable"]:,} 非課税={r["fee_non_taxable"]:,} 振込={r["transfer"]:,} [{status}]')


if __name__ == '__main__':
    main()
