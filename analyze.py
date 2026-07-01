"""
収集済みの試合データ＋タイムラインを分析し、再設計ダッシュボード用のデータと
CSVを生成する。

出力 (output/ 配下):
- senseki.csv        : 全選手×全試合の明細（@10指標含む）
- player_summary.csv : 選手別サマリー
- dashboard.html     : 4ページ構成の再設計ダッシュボード

実行: python analyze.py
"""
import json
import os

import pandas as pd

import common
import metrics
import dashboard
import ddragon


def load_champ_map(cfg):
    """英語ID→日本語名のマップを返す。実行時キャッシュ→バンドルfallback→無ければ取得を試行。"""
    m = {}
    try:
        import champions_ja
        m.update(champions_ja.CHAMP_JA_FALLBACK)
    except Exception:
        pass
    cache = load_json(os.path.join(cfg["data_dir"], "champion_names_ja.json"))
    if not cache:
        cache = ddragon.fetch_champion_names(cfg)  # analyze単体実行でも日本語化できるよう試行
    if cache:
        m.update(cache)
    return m


def localize_champions(records, champ_map):
    """records 内のチャンピオン英語名を日本語名に変換する。"""
    def ja(name):
        return champ_map.get(name, name) if name else name
    def loc_pool(pool):
        for c in pool:
            c["champ"] = ja(c.get("champ"))
    for pr in records:
        for mrec in pr["matches"]:
            mrec["champion"] = ja(mrec.get("champion"))
            mrec["opponentChampion"] = ja(mrec.get("opponentChampion"))
        loc_pool(pr["champ_pool"])
        for rd in pr.get("byRole", {}).values():
            loc_pool(rd["champ_pool"])


def _avg(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _round(v, n=2):
    return round(v, n) if v is not None else None


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def build_player_records(cfg, players, puuids, match_ids):
    key_to_puuid = {k: info["puuid"] for k, info in puuids.items()}
    records = []

    for p in players:
        key = f"{p['name']}#{p['tagline']}"
        puuid = key_to_puuid.get(key)
        if not puuid:
            continue
        role_norm = metrics.ROLE_NORM.get(p.get("role", ""), "")
        is_coach = (p.get("role", "") == "コーチ") or (role_norm == "")
        meta = {
            "nickname": p.get("nickname") or p["name"],
            "name": p["name"], "team": p.get("team", ""),
            "role_norm": role_norm, "isCoach": is_coach,
        }

        ids = match_ids.get(key, [])
        match_recs = []
        for mid in ids:
            match = load_json(common.match_cache_path(cfg, mid))
            if not match or "info" not in match:
                continue
            if metrics.is_bot_match(match):   # AI戦（Co-op vs AI）は除外
                continue
            if not metrics.is_allowed_queue(match):   # ノーマル/スイフトプレイ/ランク以外は除外
                continue
            part = metrics.find_participant(match, puuid)
            if part is None:
                continue
            timeline = load_json(common.timeline_cache_path(cfg, mid))
            rec = metrics.build_match_record(match, timeline, part, meta)
            match_recs.append(rec)

        # 指定レーン以外の戦績を除外（選手のみ。コーチは担当レーン指定が無いため全試合を保持）
        if not is_coach and role_norm:
            match_recs = [r for r in match_recs if r.get("playedRole") == role_norm]

        if not match_recs:
            continue
        # 時系列（古い→新しい）に並べ、試合番号を付与
        match_recs.sort(key=lambda r: r["gameCreation"])
        for i, r in enumerate(match_recs, 1):
            r["gameIndex"] = i

        # 実際に担当したロール(playedRole)ごとに集計（ロールを変えると戦績が変わるように）
        by_role = {}
        for role in metrics.ROLES:
            rs = [r for r in match_recs if r.get("playedRole") == role]
            if rs:
                by_role[role] = {
                    "games": len(rs),
                    "agg": aggregate_player(rs),
                    "champ_pool": champion_pool(rs),
                }
        # 主ロール = 最も多く担当したロール（無ければ players.csv のロール）
        primary = max(by_role.items(), key=lambda kv: kv[1]["games"])[0] if by_role else role_norm

        records.append({
            "nickname": meta["nickname"], "gameName": p["name"],
            "team": meta["team"], "role": role_norm, "isCoach": is_coach,
            "primaryRole": primary,
            "rolesPlayed": sorted(by_role.keys(), key=lambda r: -by_role[r]["games"]),
            "matches": match_recs,
            "agg": aggregate_player(match_recs),
            "champ_pool": champion_pool(match_recs),
            "byRole": by_role,
        })
    return records


def aggregate_player(recs):
    n = len(recs)
    wins = sum(1 for r in recs if r["win"])
    return {
        "games": n,
        "wins": wins,
        "winrate": _round(wins / n * 100, 1) if n else None,
        "kda": _round(_avg([r["kda"] for r in recs]), 2),
        "kills": _round(_avg([r["kills"] for r in recs]), 1),
        "deaths": _round(_avg([r["deaths"] for r in recs]), 1),
        "assists": _round(_avg([r["assists"] for r in recs]), 1),
        "kp": _round(_avg([r["killParticipation"] for r in recs]), 1),
        "csPerMin": _round(_avg([r["csPerMin"] for r in recs]), 1),
        "goldPerMin": _round(_avg([r["goldPerMin"] for r in recs]), 1),
        "dmgPerMin": _round(_avg([r["dmgPerMin"] for r in recs]), 1),
        "dmgDealt": int(_avg([r["dmgToChamp"] for r in recs]) or 0),
        "dmgTaken": int(_avg([r.get("dmgTaken", 0) for r in recs]) or 0),
        "dmgShare": _round(_avg([r["dmgShare"] for r in recs]), 1),
        "visionPerMin": _round(_avg([r["visionPerMin"] for r in recs]), 2),
        "wardsPlaced": _round(_avg([r["wardsPlaced"] for r in recs]), 1),
        "controlWards": _round(_avg([r["controlWards"] for r in recs]), 1),
        "csAt10": _round(_avg([r["csAt10"] for r in recs]), 1),
        "goldDiffAt10": _round(_avg([r["goldDiffAt10"] for r in recs]), 0),
        "levelDiffAt10": _round(_avg([r["levelDiffAt10"] for r in recs]), 2),
        "death10": _round(_avg([r["death10"] for r in recs]), 2),
    }


def champion_pool(recs):
    pool = {}
    for r in recs:
        c = r["champion"]
        pool.setdefault(c, []).append(r)
    out = []
    for c, rs in pool.items():
        n = len(rs)
        wins = sum(1 for r in rs if r["win"])
        out.append({
            "champ": c,
            "champId": rs[0].get("championId", c),   # アイコン用の英語ID
            "plays": n, "wins": wins, "losses": n - wins,
            "winrate": round(wins / n * 100, 1),
            "kda": _round(_avg([r["kda"] for r in rs]), 2),
            "avgKills": _round(_avg([r["kills"] for r in rs]), 1),
            "avgDeaths": _round(_avg([r["deaths"] for r in rs]), 1),
            "avgAssists": _round(_avg([r["assists"] for r in rs]), 1),
            "maxKills": max((r["kills"] for r in rs), default=0),
            "maxDeaths": max((r["deaths"] for r in rs), default=0),
            "csPerMin": _round(_avg([r["csPerMin"] for r in rs]), 1),
            "avgCs": int(_avg([r["totalCs"] for r in rs]) or 0),
            "avgDmg": int(_avg([r["dmgToChamp"] for r in rs]) or 0),
            "avgGold": int(_avg([r["goldEarned"] for r in rs]) or 0),
        })
    out.sort(key=lambda x: (x["plays"], x["winrate"]), reverse=True)
    return out


def write_csvs(cfg, records):
    rows = []
    for pr in records:
        for r in pr["matches"]:
            row = {k: v for k, v in r.items() if k not in ("deathBuckets", "items")}
            row["items"] = "|".join(str(x) for x in r["items"])
            rows.append(row)
    df = pd.DataFrame(rows)
    out = cfg["output_dir"]
    df.to_csv(os.path.join(out, "senseki.csv"), index=False, encoding="utf-8-sig")

    srows = []
    for pr in records:
        a = pr["agg"]
        top = ", ".join(f"{c['champ']}({c['plays']})" for c in pr["champ_pool"][:3])
        srows.append({
            "選手": pr["nickname"], "チーム": pr["team"], "ロール": pr["role"],
            "コーチ": "○" if pr["isCoach"] else "",
            "試合数": a["games"], "勝率%": a["winrate"], "KDA": a["kda"],
            "平均デス": a["deaths"], "CS/min": a["csPerMin"], "CS@10": a["csAt10"],
            "ゴールド差@10": a["goldDiffAt10"], "キル関与率%": a["kp"],
            "ダメージシェア%": a["dmgShare"], "視界/min": a["visionPerMin"],
            "ワード設置/試合": a["wardsPlaced"], "使用上位": top,
        })
    pd.DataFrame(srows).to_csv(os.path.join(out, "player_summary.csv"),
                              index=False, encoding="utf-8-sig")


def main():
    cfg = common.load_config()
    puuids = load_json(common.puuids_path(cfg))
    match_ids = load_json(common.match_ids_path(cfg))
    if not puuids or not match_ids:
        raise SystemExit("収集データが見つかりません。先に `python collect.py` を実行してください。")

    players = common.load_players(cfg["players_file"])
    records = build_player_records(cfg, players, puuids, match_ids)
    if not records:
        raise SystemExit("解析対象データがありません。collect.py でデータを取得してください。")

    # チャンピオン名を日本語化
    champ_map = load_champ_map(cfg)
    localize_champions(records, champ_map)
    # チャンピオンのアーキタイプ(Tank/Mage/Marksman等)。取得できなければ空dict（機能スキップ）。
    champ_tags = ddragon.load_champion_tags(cfg)

    write_csvs(cfg, records)
    total_games = sum(pr["agg"]["games"] for pr in records)
    print(f"選手数: {len(records)} / 総試合行数: {total_games}")
    print(f"CSV出力先: {cfg['output_dir']}")

    dashboard.generate(cfg, records, champ_map, champ_tags)
    print("ダッシュボード生成完了: output/dashboard.html")


if __name__ == "__main__":
    main()
