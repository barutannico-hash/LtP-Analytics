"""共通ユーティリティ: 設定読み込み・選手リスト読み込み・パス解決。"""
import csv
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config(path="config.json"):
    """config.json を読み込む。"""
    cfg_path = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 環境変数があれば優先（GitHub Actions等でキーを直書きしないため）
    if os.environ.get("RIOT_API_KEY"):
        cfg["api_key"] = os.environ["RIOT_API_KEY"].strip()
    if os.environ.get("RIOT_REGION"):
        cfg["region"] = os.environ["RIOT_REGION"].strip()
    if os.environ.get("MATCH_COUNT"):
        try:
            cfg["match_count"] = int(os.environ["MATCH_COUNT"])
        except ValueError:
            pass

    # 既定値
    cfg.setdefault("region", "asia")
    cfg.setdefault("match_count", 100)
    cfg.setdefault("queue", None)
    cfg.setdefault("players_file", "players.csv")
    cfg.setdefault("data_dir", "data")
    cfg.setdefault("output_dir", "output")

    # data_dir / output_dir を絶対パス化
    cfg["data_dir"] = _abs(cfg["data_dir"])
    cfg["output_dir"] = _abs(cfg["output_dir"])
    os.makedirs(cfg["data_dir"], exist_ok=True)
    os.makedirs(cfg["output_dir"], exist_ok=True)
    os.makedirs(os.path.join(cfg["data_dir"], "matches"), exist_ok=True)
    os.makedirs(os.path.join(cfg["data_dir"], "timelines"), exist_ok=True)
    return cfg


def load_players(players_file):
    """players.csv を読み込む。
    必須列: name, tagline / 任意列: team, role, nickname
    """
    path = _abs(players_file)
    players = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            tagline = (row.get("tagline") or "").strip()
            if not name or not tagline:
                continue
            nickname = (row.get("nickname") or "").strip() or name
            players.append({
                "name": name,
                "tagline": tagline,
                "nickname": nickname,
                "team": (row.get("team") or "").strip(),
                "role": (row.get("role") or "").strip(),
            })
    return players


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def puuids_path(cfg):
    return os.path.join(cfg["data_dir"], "puuids.json")


def match_ids_path(cfg):
    return os.path.join(cfg["data_dir"], "match_ids.json")


def match_cache_path(cfg, match_id):
    return os.path.join(cfg["data_dir"], "matches", f"{match_id}.json")


def timeline_cache_path(cfg, match_id):
    return os.path.join(cfg["data_dir"], "timelines", f"{match_id}.json")
