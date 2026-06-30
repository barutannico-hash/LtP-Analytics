"""
試合データ(match-v5)とタイムライン(match-v5 timeline)から、
再設計ダッシュボードが必要とする各指標を算出するモジュール。

設計依頼書(dashboard_design_spec.md)のデータ要件に対応:
- CS@10 / ゴールド@10 / レベル@10 / 対面との差@10
- デスのタイムスタンプ(2分バケット) / デス@10
- ダメージシェア% / キル関与率%
- 視界・ワード・コントロールワード / 最終ビルド / 対面チャンプ
"""

# teamPosition -> 表示ロール
ROLE_DISP = {
    "TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid",
    "BOTTOM": "Bot", "UTILITY": "Support",
}
# players.csv の role -> 正規ロール
ROLE_NORM = {
    "Top": "Top", "Jungle": "Jungle", "Mid": "Mid", "Bot": "Bot",
    "Sup": "Support", "Support": "Support",
    "TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "Bot", "UTILITY": "Support",
}
ROLES = ["Top", "Jungle", "Mid", "Bot", "Support"]


def safe_div(a, b):
    return a / b if b else 0.0


# Co-op vs AI（対AI / BOT戦）のキューID
BOT_QUEUES = {31, 32, 33, 830, 840, 850, 870, 880, 890}


def is_bot_match(match):
    """対AI戦（Co-op vs AI）かどうか。queueId または BOT参加者で判定。"""
    info = match.get("info", {})
    if info.get("queueId") in BOT_QUEUES:
        return True
    for p in info.get("participants", []):
        # Co-op vs AI のBOTは puuid が "BOT"
        if p.get("puuid") == "BOT":
            return True
    return False


def find_participant(match, puuid):
    for p in match["info"]["participants"]:
        if p.get("puuid") == puuid:
            return p
    return None


def find_opponent(match, part):
    """同じ teamPosition の敵チーム参加者を返す。"""
    pos = part.get("teamPosition")
    tid = part.get("teamId")
    if not pos:
        return None
    for p in match["info"]["participants"]:
        if p.get("teamId") != tid and p.get("teamPosition") == pos:
            return p
    return None


def team_aggregates(match, part):
    """同チームの与ダメ合計・キル合計（ダメージシェア/KP算出用）。"""
    tid = part.get("teamId")
    dmg = sum(p.get("totalDamageDealtToChampions", 0)
              for p in match["info"]["participants"] if p.get("teamId") == tid)
    kills = sum(p.get("kills", 0)
                for p in match["info"]["participants"] if p.get("teamId") == tid)
    return dmg, kills


def _pid_of(timeline, puuid):
    """timeline 内の participantId(1-10) を puuid から引く。"""
    meta = timeline.get("metadata", {}).get("participants", [])
    if puuid in meta:
        return meta.index(puuid) + 1
    return None


def _frame_at(frames, target_ms=600000):
    """target_ms に最も近いフレームを返す。"""
    if not frames:
        return None
    best = min(frames, key=lambda f: abs(f.get("timestamp", 0) - target_ms))
    return best


def _pframe(frame, pid):
    if not frame or pid is None:
        return None
    return frame.get("participantFrames", {}).get(str(pid))


def timeline_metrics(timeline, part_puuid, opp_puuid):
    """タイムラインから @10 指標とデス情報を算出して dict で返す。

    取得できない場合は None 値で埋める（古い試合・タイムライン欠損に対応）。
    """
    out = {
        "csAt10": None, "goldAt10": None, "levelAt10": None,
        "goldDiffAt10": None, "levelDiffAt10": None,
        "death10": None, "deathBuckets": [], "deathTimestamps": [], "firstBlood": None,
    }
    if not timeline:
        return out

    info = timeline.get("info", {})
    frames = info.get("frames", [])
    pid = _pid_of(timeline, part_puuid)
    opp_pid = _pid_of(timeline, opp_puuid) if opp_puuid else None
    if pid is None or not frames:
        return out

    f10 = _frame_at(frames, 600000)
    pf = _pframe(f10, pid)
    if pf:
        cs = pf.get("minionsKilled", 0) + pf.get("jungleMinionsKilled", 0)
        out["csAt10"] = cs
        out["goldAt10"] = pf.get("totalGold")
        out["levelAt10"] = pf.get("level")
        opf = _pframe(f10, opp_pid)
        if opf:
            if out["goldAt10"] is not None and opf.get("totalGold") is not None:
                out["goldDiffAt10"] = out["goldAt10"] - opf.get("totalGold")
            if out["levelAt10"] is not None and opf.get("level") is not None:
                out["levelDiffAt10"] = out["levelAt10"] - opf.get("level")

    # デスイベント収集 + ファーストブラッド関与
    deaths = []
    first_kill_seen = False
    first_blood = False
    for fr in frames:
        for ev in fr.get("events", []):
            if ev.get("type") != "CHAMPION_KILL":
                continue
            ts = ev.get("timestamp", 0)
            if not first_kill_seen:
                first_kill_seen = True
                if ev.get("killerId") == pid or pid in (ev.get("assistingParticipantIds") or []):
                    first_blood = True
            if ev.get("victimId") == pid:
                deaths.append(ts)
    out["deathTimestamps"] = deaths
    out["deathBuckets"] = [int(ts // 120000) for ts in deaths]
    out["death10"] = sum(1 for ts in deaths if ts <= 600000)
    out["firstBlood"] = first_blood
    return out


def build_match_record(match, timeline, part, meta):
    """1試合×1選手の全指標をまとめた dict を作る。"""
    info = match["info"]
    dur_s = info.get("gameDuration", 0) or 0
    dur_min = dur_s / 60 if dur_s else 0
    ch = part.get("challenges", {}) or {}

    opp = find_opponent(match, part)
    opp_champ = opp.get("championName") if opp else None
    opp_puuid = opp.get("puuid") if opp else None

    team_dmg, team_kills = team_aggregates(match, part)
    dmg = part.get("totalDamageDealtToChampions", 0)
    k = part.get("kills", 0)
    d = part.get("deaths", 0)
    a = part.get("assists", 0)
    total_cs = part.get("totalMinionsKilled", 0) + part.get("neutralMinionsKilled", 0)

    tl = timeline_metrics(timeline, part.get("puuid"), opp_puuid)

    items = [part.get(f"item{i}", 0) for i in range(7)]

    return {
        "matchId": match["metadata"]["matchId"],
        "gameCreation": info.get("gameCreation", 0),
        "gameDuration": dur_s,
        "nickname": meta.get("nickname") or meta.get("name"),
        "team": meta.get("team", ""),
        "role": meta.get("role_norm", ""),
        "isCoach": meta.get("isCoach", False),
        "champion": part.get("championName"),
        "championId": part.get("championName"),      # アイコン用の英語ID（日本語化しても保持）
        "opponentChampion": opp_champ,
        "opponentChampionId": opp_champ,             # アイコン用の英語ID
        "playedRole": ROLE_DISP.get(part.get("teamPosition") or "", ""),  # ポジション不明(ARAM等)は空
        "win": bool(part.get("win")),
        "kills": k, "deaths": d, "assists": a,
        "kda": round(safe_div(k + a, max(d, 1)), 2),
        "totalCs": total_cs,
        "csPerMin": round(safe_div(total_cs, dur_min), 2),
        "goldEarned": part.get("goldEarned", 0),
        "goldPerMin": round(safe_div(part.get("goldEarned", 0), dur_min), 1),
        "dmgToChamp": dmg,
        "dmgTaken": part.get("totalDamageTaken", 0),       # 被ダメージ（合計）
        "dmgPerMin": round(safe_div(dmg, dur_min), 1),
        "dmgShare": round(safe_div(dmg, team_dmg) * 100, 1),
        "killParticipation": round(safe_div(k + a, team_kills) * 100, 1),
        "visionScore": part.get("visionScore", 0),
        "visionPerMin": round(safe_div(part.get("visionScore", 0), dur_min), 2),
        "wardsPlaced": part.get("wardsPlaced", 0),
        "wardsKilled": part.get("wardsKilled", 0),
        "controlWards": part.get("visionWardsBoughtInGame", 0),
        "ccScore": part.get("timeCCingOthers", 0),
        "towerDmg": part.get("damageDealtToTurrets", 0),
        "items": items,
        # timeline 由来
        "csAt10": tl["csAt10"],
        "goldAt10": tl["goldAt10"],
        "levelAt10": tl["levelAt10"],
        "goldDiffAt10": tl["goldDiffAt10"],
        "levelDiffAt10": tl["levelDiffAt10"],
        "death10": tl["death10"],
        "deathBuckets": tl["deathBuckets"],
        "firstBlood": tl["firstBlood"],
    }
