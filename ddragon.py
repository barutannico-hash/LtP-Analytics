"""Data Dragon から最新のチャンピオン日本語名を取得してキャッシュする。

Riot API ではなく公開CDN(ddragon)なのでレート制限の対象外。
取得した {英語ID: 日本語名} を data/champion_names_ja.json に保存する。
"""
import json
import os

import requests

DEFAULT_VERSION = "16.13.1"


def _version_path(cfg):
    return os.path.join(cfg["data_dir"], "ddragon_version.txt")


def fetch_champion_names(cfg, lang="ja_JP", timeout=15):
    out_path = os.path.join(cfg["data_dir"], "champion_names_ja.json")
    try:
        vers = requests.get("https://ddragon.leagueoflegends.com/api/versions.json",
                            timeout=timeout).json()
        ver = vers[0]
        data = requests.get(
            f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/{lang}/champion.json",
            timeout=timeout).json()
        m = {cid: info["name"] for cid, info in data["data"].items()}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        with open(_version_path(cfg), "w", encoding="utf-8") as f:
            f.write(ver)
        print(f"チャンピオン日本語名を取得: {len(m)}体 (v{ver})")
        return m
    except Exception as e:
        print(f"  [情報] チャンピオン名の取得に失敗（オフライン等）: {e}。フォールバックを使用します。")
        return None


def get_version(cfg):
    """キャッシュ済みの Data Dragon バージョンを返す（無ければ既定値）。"""
    try:
        with open(_version_path(cfg), "r", encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    return DEFAULT_VERSION
