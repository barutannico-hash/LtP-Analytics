"""
ワンクリック更新スクリプト。
collect.py（最新試合の収集）→ analyze.py（集計・ダッシュボード生成）を連続実行し、
最後に dashboard.html をブラウザで開く。

実行: python update.py
（Windows なら update.bat をダブルクリックでもOK）
"""
import os
import webbrowser

import collect
import analyze
import common


def main():
    print("=== 戦績データを最新に更新します ===\n")
    collect.main()
    print("\n=== 分析・ダッシュボード生成 ===\n")
    analyze.main()

    cfg = common.load_config()
    html = os.path.join(cfg["output_dir"], "dashboard.html")
    if os.path.exists(html):
        print(f"\nダッシュボードを開きます: {html}")
        try:
            webbrowser.open("file://" + os.path.abspath(html))
        except Exception:
            pass


if __name__ == "__main__":
    main()
