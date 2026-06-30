"""
Riot API から各選手の直近 N 試合（既定100）の戦績データを収集する。

特徴:
- レート制限(20req/s, 100req/2min)に対応した安全なリクエストラッパー
- 429 (Rate Limit Exceeded) を Retry-After に従って自動リトライ
- 取得済みデータはキャッシュし、再実行時は再取得しない（レジューム対応）
  -> APIキーは24時間で失効するため、途中で切れても続きから再開できる

実行: python collect.py
"""
import json
import os
import time

from riotwatcher import LolWatcher, ApiError, RiotWatcher

import common
import ddragon


class RateLimiter:
    """シンプルなレート制限管理 + 429自動リトライ。"""

    def __init__(self, per_second=18, per_two_min=95):
        # Riot個人キーの実上限(20/s, 100/2min)より少し低めに設定して余裕を持たせる
        self.per_second = per_second
        self.per_two_min = per_two_min
        self.sec_window = []      # 直近1秒のリクエスト時刻
        self.two_min_window = []  # 直近120秒のリクエスト時刻

    def _wait_if_needed(self):
        now = time.time()
        self.sec_window = [t for t in self.sec_window if now - t < 1.0]
        self.two_min_window = [t for t in self.two_min_window if now - t < 120.0]

        if len(self.sec_window) >= self.per_second:
            sleep = 1.0 - (now - self.sec_window[0]) + 0.02
            if sleep > 0:
                time.sleep(sleep)
        if len(self.two_min_window) >= self.per_two_min:
            sleep = 120.0 - (now - self.two_min_window[0]) + 0.1
            if sleep > 0:
                print(f"  [rate] 2分制限のため {sleep:.0f}s 待機します...")
                time.sleep(sleep)

    def call(self, func, *args, **kwargs):
        """レート制限を守りつつ func を呼ぶ。429は自動リトライ。"""
        for attempt in range(6):
            self._wait_if_needed()
            now = time.time()
            self.sec_window.append(now)
            self.two_min_window.append(now)
            try:
                return func(*args, **kwargs)
            except ApiError as err:
                status = getattr(err.response, "status_code", None)
                if status == 429:
                    retry_after = int(err.response.headers.get("Retry-After", "10"))
                    print(f"  [429] レート制限。{retry_after}s 待機して再試行 ({attempt + 1}/6)")
                    time.sleep(retry_after + 1)
                    continue
                if status in (500, 502, 503, 504):
                    print(f"  [{status}] サーバーエラー。5s 待機して再試行 ({attempt + 1}/6)")
                    time.sleep(5)
                    continue
                raise
        raise RuntimeError("リトライ上限に達しました。時間をおいて再実行してください。")


def get_puuids(cfg, players, rl, account_api):
    """各選手の PUUID を取得（キャッシュあり）。"""
    path = common.puuids_path(cfg)
    cache = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cache = json.load(f)

    for p in players:
        key = f"{p['name']}#{p['tagline']}"
        if key in cache and cache[key].get("puuid"):
            # PUUIDはキャッシュ利用。team/role/nickname は players.csv の最新で更新
            cache[key]["nickname"] = p.get("nickname", p["name"])
            cache[key]["team"] = p.get("team", "")
            cache[key]["role"] = p.get("role", "")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            print(f"PUUID (cache): {key}")
            continue
        try:
            acc = rl.call(account_api.by_riot_id, region=cfg["region"],
                          game_name=p["name"], tag_line=p["tagline"])
            cache[key] = {
                "name": p["name"], "tagline": p["tagline"], "puuid": acc["puuid"],
                "nickname": p.get("nickname", p["name"]),
                "team": p.get("team", ""), "role": p.get("role", ""),
            }
            print(f"PUUID: {key} -> {acc['puuid'][:16]}...")
        except ApiError as err:
            status = getattr(err.response, "status_code", None)
            print(f"  [WARN] {key} のPUUID取得に失敗 (status={status})。スキップします。")
            continue
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    return cache


def get_match_ids(cfg, puuids, players, rl, match_api):
    """各選手の「直近 match_count 試合」の MatchID を毎回最新で取得する。

    実行（更新）するたびに最新の試合リストを取り直すため、新しい試合が
    自動的に取り込まれる。古い試合はリストから外れる（=直近N戦を維持）。
    matchlist 自体は1人2リクエスト程度と軽いので毎回更新しても負荷は小さい。

    players.csv に現在載っている選手だけを対象とし、不正なPUUIDは
    スキップする（過去の不要なキャッシュ等で停止しないようにするため）。
    """
    path = common.match_ids_path(cfg)
    cache = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cache = json.load(f)

    valid_keys = [f"{p['name']}#{p['tagline']}" for p in players]
    count = cfg["match_count"]
    for key in valid_keys:
        info = puuids.get(key)
        if not info or not info.get("puuid"):
            print(f"  [skip] {key} のPUUID未取得。スキップします。")
            continue
        puuid = info["puuid"]
        ids = []
        try:
            # Riot APIの matchlist は1回あたり最大100件。countが100超なら分割取得。
            for start in range(0, count, 100):
                batch = min(100, count - start)
                kwargs = dict(region=cfg["region"], puuid=puuid, start=start, count=batch)
                if cfg.get("queue"):
                    kwargs["queue"] = cfg["queue"]
                matches = rl.call(match_api.matchlist_by_puuid, **kwargs)
                ids.extend(matches)
                if len(matches) < batch:
                    break  # これ以上試合がない
        except ApiError as err:
            status = getattr(err.response, "status_code", None)
            print(f"  [WARN] {key} の試合リスト取得に失敗 (status={status})。スキップ。")
            continue
        new_count = len([m for m in ids if m not in set(cache.get(key, []))])
        cache[key] = ids  # 最新リストで上書き（直近N戦）
        print(f"MatchID: {key} ({len(ids)}件 / 新規{new_count}件)")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    return cache


def fetch_matches(cfg, match_ids_by_player, rl, match_api):
    """全試合の「試合データ」と「タイムライン」を取得し、1試合=1JSONでキャッシュ保存。

    タイムラインは CS@10・ゴールド差@10・デスのタイムスタンプ等の算出に必須。
    どちらも不変データなので、既に取得済みの試合は再取得しない（更新時は新規分のみ）。
    """
    all_ids = []
    seen = set()
    for ids in match_ids_by_player.values():
        for mid in ids:
            if mid not in seen:
                seen.add(mid)
                all_ids.append(mid)

    total = len(all_ids)
    print(f"\nユニーク試合数: {total} 件（試合データ＋タイムライン）を取得します。")
    m_new, m_cache, t_new, t_cache = 0, 0, 0, 0
    for i, mid in enumerate(all_ids, 1):
        # --- 試合データ ---
        cpath = common.match_cache_path(cfg, mid)
        if os.path.exists(cpath):
            m_cache += 1
        else:
            try:
                data = rl.call(match_api.by_id, region=cfg["region"], match_id=mid)
                with open(cpath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                m_new += 1
            except ApiError as err:
                status = getattr(err.response, "status_code", None)
                print(f"  [WARN] {mid} 試合データ取得失敗 (status={status})。スキップ。")

        # --- タイムライン ---
        tpath = common.timeline_cache_path(cfg, mid)
        if os.path.exists(tpath):
            t_cache += 1
        else:
            try:
                tl = rl.call(match_api.timeline_by_match, region=cfg["region"], match_id=mid)
                with open(tpath, "w", encoding="utf-8") as f:
                    json.dump(tl, f, ensure_ascii=False)
                t_new += 1
            except ApiError as err:
                status = getattr(err.response, "status_code", None)
                print(f"  [WARN] {mid} タイムライン取得失敗 (status={status})。スキップ。")

        if i % 25 == 0 or i == total:
            print(f"  進捗 {i}/{total} (試合:新規{m_new}/既存{m_cache} | TL:新規{t_new}/既存{t_cache})")
    print(f"\n取得完了: 試合データ 新規{m_new}/既存{m_cache} ｜ タイムライン 新規{t_new}/既存{t_cache}")
    return all_ids


def main():
    cfg = common.load_config()
    if cfg["api_key"].startswith("RGAPI-xxxx"):
        raise SystemExit("config.json の api_key を実際のRiot APIキーに置き換えてください。")

    players = common.load_players(cfg["players_file"])
    print(f"対象選手: {len(players)} 名 / リージョン: {cfg['region']} / 1人あたり {cfg['match_count']} 試合\n")

    rl = RateLimiter()
    riotwatcher = RiotWatcher(cfg["api_key"])
    lolwatcher = LolWatcher(cfg["api_key"])

    print("=== Step 1: PUUID 取得 ===")
    puuids = get_puuids(cfg, players, rl, riotwatcher.account)

    print("\n=== Step 2: MatchID 取得 ===")
    match_ids = get_match_ids(cfg, puuids, players, rl, lolwatcher.match)

    print("\n=== Step 3: 試合データ取得 ===")
    fetch_matches(cfg, match_ids, rl, lolwatcher.match)

    print("\n=== Step 4: チャンピオン日本語名の取得 ===")
    ddragon.fetch_champion_names(cfg)

    print("\nすべての収集が完了しました。続けて `python analyze.py` を実行してください。")


if __name__ == "__main__":
    main()
