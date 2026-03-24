"""
下载上市公司年报/半年报 PDF 文档。

用法示例:
    # 命令行模式（支持多年份）
    python download_annual_reports.py \
        --codes 000001 600519 \
        --years 2022 2023 2024 \
        --type annual \
        --token YOUR_ACCESS_TOKEN \
        --output ./reports

    # 无参数直接运行，执行 test_download() 测试示例
    python download_annual_reports.py
"""

import argparse
import os
import re
import time
import webbrowser
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
CNINFO_HOME = "https://www.cninfo.com.cn"


def open_browser(url: str = CNINFO_HOME):
    """在系统默认浏览器中打开指定 URL。"""
    print(f"正在打开浏览器: {url}")
    webbrowser.open(url)


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


def download_reports(codes: list, years: list, report_type: str, access_token: str, output_dir: str = "./reports"):
    """
    批量下载年报/半年报。

    Args:
        codes: 股票代码列表, 如 ["000001", "600519"]
        years: 年份列表, 如 [2022, 2023, 2024]
        report_type: "annual"(年报) 或 "semi_annual"(半年报)
        access_token: cninfo API access_token
        output_dir: PDF 保存目录
    """
    os.makedirs(output_dir, exist_ok=True)

    start_suffix, end_suffix = DATE_RANGES[report_type]
    type_label = "年报" if report_type == "annual" else "半年报"

    print(f"报告类型: {type_label}")
    print(f"股票代码: {', '.join(codes)}")
    print(f"年份列表: {', '.join(str(y) for y in years)}")
    print(f"保存目录: {output_dir}")
    print("=" * 60)

    total_downloaded = 0

    for year in years:
        # 年报在 year+1 年的 3-6 月公布；半年报在 year 年的 7-9 月公布
        pub_year = year + 1 if report_type == "annual" else year
        sdate = f"{pub_year}{start_suffix}"
        edate = f"{pub_year}{end_suffix}"

        print(f"\n--- {year} 年{type_label} (查询日期: {sdate}~{edate}) ---")

        for code in codes:
            print(f"\n[{code}] 正在查询公告...")
            records = query_announcements(code, sdate, edate, access_token)
            print(f"  共获取 {len(records)} 条公告记录")

            reports = filter_reports(records, report_type, year)
            print(f"  筛选出 {len(reports)} 份{type_label}")

            if not reports:
                print(f"  未找到 {code} 的 {year} 年{type_label}")
                continue

            for report in reports:
                title_no_spaces = report['title'].replace(" ", "")
                filename = sanitize_filename(
                    f"{report['seccode']}_{title_no_spaces}.pdf"
                )
                save_path = os.path.join(output_dir, filename)

                if os.path.exists(save_path):
                    print(f"  已存在，跳过: {filename}")
                    continue

                print(f"  正在下载: {report['title']}")
                if download_pdf(report["url"], save_path):
                    print(f"  已保存: {filename}")
                    total_downloaded += 1
                else:
                    print(f"  下载失败: {filename}")

                time.sleep(1)

    print(f"\n{'=' * 60}")
    print(f"下载完成，共下载 {total_downloaded} 份报告到 {output_dir}")
    return total_downloaded


def main():
    parser = argparse.ArgumentParser(description="下载上市公司年报/半年报 PDF")
    parser.add_argument("--open-browser", action="store_true",
                        help="在默认浏览器中打开巨潮资讯网首页（可用于获取 access_token）")
    parser.add_argument("--codes", nargs="+", help="股票代码列表，如 000001 600519")
    parser.add_argument("--years", nargs="+", type=int, help="年份列表，如 2022 2023 2024")
    parser.add_argument("--type", choices=["annual", "semi_annual"], default="annual",
                        help="报告类型: annual(年报) 或 semi_annual(半年报)")
    parser.add_argument("--token", help="cninfo API access_token")
    parser.add_argument("--output", default="./reports", help="下载保存目录")
    args = parser.parse_args()

    if args.open_browser:
        open_browser()
        return

    if not args.codes or not args.years or not args.token:
        parser.error("--codes、--years 和 --token 为必填参数（或使用 --open-browser 打开浏览器）")

    download_reports(args.codes, args.years, args.type, args.token, args.output)


# ============================================================
# 测试调用示例（直接运行时使用）
# 使用前请将 ACCESS_TOKEN 替换为你的真实 token
# ============================================================
def test_download():
    """测试调用示例：下载多只股票、多个年份的年报。"""

    ACCESS_TOKEN = "your_access_token_here"  # <-- 替换为你的 token

    # 股票代码列表
    stock_codes = [
        "000001",  # 平安银行
        "600519",  # 贵州茅台
        "000858",  # 五粮液
    ]

    # 年份列表
    years = [2022, 2023, 2024]

    # 报告类型: "annual"(年报) 或 "semi_annual"(半年报)
    report_type = "annual"

    # 保存目录
    output_dir = "./reports"

    download_reports(stock_codes, years, report_type, ACCESS_TOKEN, output_dir)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 有命令行参数时走 argparse
        main()
    else:
        # 无参数时运行测试示例
        test_download()
