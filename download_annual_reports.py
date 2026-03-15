"""
下载上市公司年报/半年报 PDF 文档。

用法示例:
    python download_annual_reports.py \
        --codes 000001 600519 \
        --year 2024 \
        --type annual \
        --token YOUR_ACCESS_TOKEN \
        --output ./reports
"""

import argparse
import os
import re
import time
import requests


API_URL = "https://webapi.cninfo.com.cn/api/info/p_info3015"

# 年报一般3-6月公布，半年报7-9月公布
DATE_RANGES = {
    "annual": ("0301", "0630"),      # 年报
    "semi_annual": ("0701", "0930"), # 半年报
}

# 公告标题关键词匹配
TITLE_PATTERNS = {
    "annual": re.compile(r"年度报告(?!.*摘要)(?!.*更正)(?!.*补充)(?!.*英文)", re.IGNORECASE),
    "semi_annual": re.compile(r"半年度报告(?!.*摘要)(?!.*更正)(?!.*补充)(?!.*英文)", re.IGNORECASE),
}

CNINFO_FILE_BASE = "https://static.cninfo.com.cn/"


def query_announcements(scode: str, sdate: str, edate: str, access_token: str) -> list:
    """调用 p_info3015 接口，获取指定股票在日期范围内的公告列表。"""
    all_records = []
    max_id = None

    while True:
        params = {
            "scode": scode,
            "sdate": sdate,
            "edate": edate,
            "format": "json",
            "access_token": access_token,
        }
        if max_id is not None:
            params["maxid"] = max_id

        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("resultcode") != 200 and data.get("resultcode") != "200":
            error_msg = data.get("resultmsg", "未知错误")
            print(f"  API 返回错误: {data.get('resultcode')} - {error_msg}")
            break

        records = data.get("records", [])
        if not records:
            break

        all_records.extend(records)

        # 如果记录数达到上限，使用增量提取
        if len(records) >= 20000:
            max_id = max(int(r.get("OBJECTID", 0)) for r in records)
        else:
            break

    return all_records


def filter_reports(records: list, report_type: str, year: int) -> list:
    """从公告列表中筛选出年报或半年报 PDF 文件。"""
    pattern = TITLE_PATTERNS[report_type]
    year_str = str(year)

    results = []
    for rec in records:
        title = rec.get("F002V", "")
        fmt = rec.get("F004V", "")
        url = rec.get("F003V", "")

        # 只要 PDF 格式
        if "PDF" not in fmt.upper():
            continue

        # 标题匹配：包含"年度报告"或"半年度报告"，且包含对应年份
        if not pattern.search(title):
            continue

        # 年报对应的报告期年份检查
        if report_type == "annual" and year_str not in title:
            continue
        if report_type == "semi_annual" and year_str not in title:
            continue

        results.append({
            "seccode": rec.get("SECCODE", ""),
            "secname": rec.get("SECNAME", ""),
            "title": title,
            "url": url,
            "date": rec.get("F001D", ""),
            "size": rec.get("F005N", 0),
        })

    return results


def download_pdf(url: str, save_path: str) -> bool:
    """下载 PDF 文件到本地。"""
    # 公告地址可能是相对路径，需要拼接基础 URL
    if not url.startswith("http"):
        url = CNINFO_FILE_BASE + url

    try:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  下载失败: {e}")
        return False


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符。"""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def main():
    parser = argparse.ArgumentParser(description="下载上市公司年报/半年报 PDF")
    parser.add_argument("--codes", nargs="+", required=True, help="股票代码列表，如 000001 600519")
    parser.add_argument("--year", type=int, required=True, help="报告年份，如 2024")
    parser.add_argument("--type", choices=["annual", "semi_annual"], default="annual",
                        help="报告类型: annual(年报) 或 semi_annual(半年报)")
    parser.add_argument("--token", required=True, help="cninfo API access_token")
    parser.add_argument("--output", default="./reports", help="下载保存目录")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    # 确定查询的日期范围
    # 年报在 year+1 年的 3-6 月公布；半年报在 year 年的 7-9 月公布
    start_suffix, end_suffix = DATE_RANGES[args.type]
    if args.type == "annual":
        pub_year = args.year + 1
    else:
        pub_year = args.year

    sdate = f"{pub_year}{start_suffix}"
    edate = f"{pub_year}{end_suffix}"

    print(f"查询参数: 类型={args.type}, 报告年份={args.year}, 查询日期范围={sdate}~{edate}")
    print(f"股票代码: {', '.join(args.codes)}")
    print(f"保存目录: {args.output}")
    print("=" * 60)

    total_downloaded = 0

    for code in args.codes:
        print(f"\n[{code}] 正在查询公告...")
        records = query_announcements(code, sdate, edate, args.token)
        print(f"  共获取 {len(records)} 条公告记录")

        reports = filter_reports(records, args.type, args.year)
        print(f"  筛选出 {len(reports)} 份报告")

        if not reports:
            print(f"  未找到 {code} 的 {args.year} 年{'年报' if args.type == 'annual' else '半年报'}")
            continue

        for report in reports:
            filename = sanitize_filename(f"{report['seccode']}_{report['secname']}_{report['title']}.pdf")
            save_path = os.path.join(args.output, filename)

            if os.path.exists(save_path):
                print(f"  已存在，跳过: {filename}")
                continue

            print(f"  正在下载: {report['title']}")
            if download_pdf(report["url"], save_path):
                print(f"  已保存: {filename}")
                total_downloaded += 1
            else:
                print(f"  下载失败: {filename}")

            # 避免请求过于频繁
            time.sleep(1)

    print(f"\n{'=' * 60}")
    print(f"下载完成，共下载 {total_downloaded} 份报告到 {args.output}")


if __name__ == "__main__":
    main()
