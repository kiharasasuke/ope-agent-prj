#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Airペイ手数料計算スクリプト
入金サイクル別・決済ブランド別に手数料を集計
月末日分離機能付き
"""

import csv
import math
import sys
import os
import re
import calendar
from collections import defaultdict
from datetime import datetime

# 手数料率の定義
RATE_CAMPAIGN = 0.0248   # キャンペーン対象（Visa, Mastercard, JCB, Amex, Diners, Discover）非課税
RATE_324 = 0.0324        # iD, QUICPay 非課税
RATE_3245 = 0.03245      # 交通系電子マネー、QR決済（2.95%+税）課税


def get_rate_info(brand):
    """決済ブランドから手数料率情報を取得"""
    brand = brand.strip()

    # キャンペーン対象（クレジットカード）: 2.48%
    campaign_brands = ['Visa', 'Mastercard(R)', 'JCB', 'American Express', 'Diners Club', 'Discover']
    for cb in campaign_brands:
        if cb in brand:
            return (RATE_CAMPAIGN, '2.48%', '非課税')

    # iD, QUICPay: 3.24%
    if 'iD' in brand or 'QUICPay' in brand:
        return (RATE_324, '3.24%', '非課税')

    # 交通系電子マネー: 3.245%
    if '交通系' in brand or '電子マネー' in brand:
        return (RATE_3245, '3.245%', '課税')

    # QR決済: 3.245%
    qr_brands = ['PayPay', 'd払い', '楽天ペイ', 'au PAY', 'COIN+', 'WeChat', 'Alipay']
    for qb in qr_brands:
        if qb in brand:
            return (RATE_3245, '3.245%', '課税')

    # デフォルト（不明なブランド）
    return (RATE_3245, '3.245%', '課税')


def detect_valid_rows(rows):
    """有効なデータ行数を検出（重複データ対策）"""
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')

    for i, row in enumerate(rows[1:], 1):
        if not row or not row[0] or not date_pattern.match(row[0]):
            return i

    return len(rows)


def is_last_day_of_month(date_str):
    """日付が月末日かどうか判定"""
    try:
        year = int(date_str[:4])
        month = int(date_str[5:7])
        day = int(date_str[8:10])
        last_day = calendar.monthrange(year, month)[1]
        return day == last_day
    except (ValueError, IndexError):
        return False


def get_accounting_label(payment_date, usage_date):
    """入金日と利用日から会計ラベルを生成（月末日分離対応）"""
    usage_month = usage_date[:7]  # YYYY-MM

    if is_last_day_of_month(usage_date):
        # 月末日は別グループ
        return f'{payment_date} (利用日:{usage_date}=月末)'
    else:
        return f'{payment_date} (利用月:{usage_month})'


def calculate_fees(input_file, output_file=None, max_rows=None):
    """手数料を計算してCSVに出力"""

    # ファイル読み込み
    with open(input_file, 'r', encoding='cp932') as f:
        reader = csv.reader(f)
        rows = list(reader)

    # 有効行数を自動検出または指定値を使用
    if max_rows:
        rows = rows[:max_rows + 1]
    else:
        valid_count = detect_valid_rows(rows)
        rows = rows[:valid_count]

    # 入金日・会計ラベル・決済ブランドごとに金額を集計
    data = defaultdict(lambda: defaultdict(int))

    for row in rows[1:]:
        if len(row) >= 9:
            payment_date = row[0]   # 入金日
            usage_date = row[4]     # 利用日
            brand = row[5]          # 決済ブランド
            amount_str = row[8]     # 金額

            if payment_date and brand and usage_date:
                try:
                    amount = int(amount_str)
                    label = get_accounting_label(payment_date, usage_date)
                    data[label][brand] += amount
                except (ValueError, TypeError):
                    pass

    # 出力ファイル名を決定
    if not output_file:
        basename = os.path.basename(input_file)
        match = re.search(r'(\d{6})', basename)
        if match:
            yyyymm = match.group(1)
        else:
            yyyymm = datetime.now().strftime('%Y%m')

        output_dir = os.path.dirname(input_file)
        output_file = os.path.join(output_dir, f'手数料集計_{yyyymm}.csv')

    # CSV出力
    output_rows = []
    output_rows.append(['入金日（利用月）', '決済ブランド', '合計金額', '課税区分', '手数料率', '手数料'])

    grand_total_amount = 0
    grand_total_fee = 0

    # 会計月別の集計用
    monthly_totals = defaultdict(lambda: {'amount': 0, 'fee': 0})

    for label in sorted(data.keys()):
        label_total_amount = 0
        label_total_fee = 0

        for brand in sorted(data[label].keys()):
            amount = data[label][brand]
            rate, rate_str, tax_type = get_rate_info(brand)
            fee = math.floor(abs(amount) * rate)
            if amount < 0:
                fee = -fee

            output_rows.append([label, brand, amount, tax_type, rate_str, fee])

            label_total_amount += amount
            label_total_fee += fee

        output_rows.append([f'{label} 小計', '', label_total_amount, '', '', label_total_fee])
        output_rows.append([])

        grand_total_amount += label_total_amount
        grand_total_fee += label_total_fee

        # 会計月を抽出して月別集計
        if '利用日:' in label and '=月末' in label:
            # 月末日の場合: 利用日の月を使用
            month_match = re.search(r'利用日:(\d{4}-\d{2})', label)
            if month_match:
                accounting_month = month_match.group(1)
        else:
            # 通常: 利用月を使用
            month_match = re.search(r'利用月:(\d{4}-\d{2})', label)
            if month_match:
                accounting_month = month_match.group(1)
            else:
                accounting_month = 'unknown'

        monthly_totals[accounting_month]['amount'] += label_total_amount
        monthly_totals[accounting_month]['fee'] += label_total_fee

    # 会計月別サマリー
    output_rows.append(['=== 会計月別サマリー ===', '', '', '', '', ''])
    for month in sorted(monthly_totals.keys()):
        totals = monthly_totals[month]
        output_rows.append([f'{month}月分', '', totals['amount'], '', '', totals['fee']])

    output_rows.append([])
    output_rows.append(['総合計', '', grand_total_amount, '', '', grand_total_fee])

    with open(output_file, 'w', encoding='cp932', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(output_rows)

    return {
        'output_file': output_file,
        'total_amount': grand_total_amount,
        'total_fee': grand_total_fee,
        'monthly_totals': dict(monthly_totals),
        'data': dict(data)
    }


def main():
    if len(sys.argv) < 2:
        print('Usage: python calculate_fee.py <input_csv> [output_csv] [max_rows]')
        print('  input_csv  : Airpay CSV file')
        print('  output_csv : Output file (optional)')
        print('  max_rows   : Max data rows to process (optional)')
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    max_rows = int(sys.argv[3]) if len(sys.argv) > 3 else None

    result = calculate_fees(input_file, output_file, max_rows)

    print(f'Output: {result["output_file"]}')
    print(f'Total Amount: {result["total_amount"]:,}')
    print(f'Total Fee: {result["total_fee"]:,}')
    print()
    print('Monthly Summary:')
    for month, totals in sorted(result['monthly_totals'].items()):
        print(f'  {month}: {totals["amount"]:,} / Fee: {totals["fee"]:,}')


if __name__ == '__main__':
    main()
