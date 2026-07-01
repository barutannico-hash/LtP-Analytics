"""
再設計版 4ページ構成ダッシュボード(dashboard.html)を生成する。
analyze.py から records を受け取り、HTMLに埋め込む。

ページ: 1.大会全体の概要 / 2.選手一覧＆比較 / 3.選手詳細 / 4.ロール別ベンチマーク
"""
import datetime
import json
import os

import metrics


# 各試合レコードからUIに必要なフィールドだけ抜き出す（埋め込みサイズ削減）
MATCH_FIELDS = [
    "matchId", "gameIndex", "gameCreation", "champion", "championId", "playedRole",
    "opponentChampion", "opponentChampionId", "win",
    "kills", "deaths", "assists", "kda", "totalCs", "csPerMin",
    "csAt10", "goldDiffAt10", "levelDiffAt10", "death10",
    "dmgShare", "killParticipation", "visionScore", "visionPerMin",
    "wardsPlaced", "controlWards", "dmgToChamp", "goldEarned",
    "deathBuckets", "firstBlood", "items",
]


# ロールごとの「重要指標」。全員共通のもの＋各レーン固有のものを合わせて使う。
# ③選手詳細のカード表示・「良くなったポイント」・「次に改善したいポイント」で
# 自分のロールに関係ない指標の伸びを過大評価しないように使う。
ROLE_PRIORITY_METRICS = {
    "common": ["winrate", "csAt10", "visionPerMin"],
    "byRole": {
        "Top": ["goldDiffAt10", "levelDiffAt10"],
        "Mid": ["goldDiffAt10", "levelDiffAt10"],
        "Jungle": ["kp", "deaths"],
        "Bot": ["csPerMin", "deaths", "dmgShare"],
        "Support": ["kp", "wardsPlaced", "controlWards"],
    },
}

# ブロンズ〜シルバー帯のおおよそのベンチマーク（編集可能: benchmarks.json で上書き）
# 勝率(winrate)はマッチメイキングにより誰でも平均50%に寄るため、ランク帯基準の
# 目標値としては馴染まないのでベンチマーク対象には含めない（重要指標としては別途使用）。
DEFAULT_BENCH = {
    "metrics": ["kda", "csPerMin", "kp", "deaths"],
    "targetTier": "Silver",
    "tiers": {
        "Bronze": {
            "Top": {"kda": 2.0, "csPerMin": 5.2, "kp": 45, "deaths": 6.2,
                     "csAt10": 62, "visionPerMin": 0.9, "goldDiffAt10": -150, "levelDiffAt10": -0.3},
            "Jungle": {"kda": 2.1, "csPerMin": 4.2, "kp": 52, "deaths": 6.0,
                        "csAt10": 38, "visionPerMin": 1.0},
            "Mid": {"kda": 2.1, "csPerMin": 5.4, "kp": 50, "deaths": 6.2,
                     "csAt10": 65, "visionPerMin": 0.9, "goldDiffAt10": -150, "levelDiffAt10": -0.3},
            "Bot": {"kda": 2.2, "csPerMin": 5.6, "kp": 50, "deaths": 6.0,
                     "csAt10": 68, "visionPerMin": 0.8, "dmgShare": 22},
            "Support": {"kda": 2.2, "csPerMin": 0.9, "kp": 55, "deaths": 6.5,
                         "csAt10": 8, "visionPerMin": 1.8, "wardsPlaced": 12, "controlWards": 1.2},
        },
        "Silver": {
            "Top": {"kda": 2.2, "csPerMin": 5.6, "kp": 47, "deaths": 5.9,
                     "csAt10": 68, "visionPerMin": 1.0, "goldDiffAt10": 0, "levelDiffAt10": 0.0},
            "Jungle": {"kda": 2.3, "csPerMin": 4.6, "kp": 55, "deaths": 5.7,
                        "csAt10": 44, "visionPerMin": 1.1},
            "Mid": {"kda": 2.3, "csPerMin": 5.9, "kp": 52, "deaths": 5.9,
                     "csAt10": 71, "visionPerMin": 1.0, "goldDiffAt10": 0, "levelDiffAt10": 0.0},
            "Bot": {"kda": 2.4, "csPerMin": 6.1, "kp": 52, "deaths": 5.7,
                     "csAt10": 74, "visionPerMin": 0.9, "dmgShare": 25},
            "Support": {"kda": 2.4, "csPerMin": 1.0, "kp": 58, "deaths": 6.2,
                         "csAt10": 12, "visionPerMin": 2.1, "wardsPlaced": 15, "controlWards": 1.6},
        },
        "Gold": {
            "Top": {"kda": 2.4, "csPerMin": 6.0, "kp": 49, "deaths": 5.6,
                     "csAt10": 74, "visionPerMin": 1.1, "goldDiffAt10": 150, "levelDiffAt10": 0.3},
            "Jungle": {"kda": 2.5, "csPerMin": 5.0, "kp": 57, "deaths": 5.4,
                        "csAt10": 50, "visionPerMin": 1.3},
            "Mid": {"kda": 2.5, "csPerMin": 6.3, "kp": 54, "deaths": 5.6,
                     "csAt10": 77, "visionPerMin": 1.1, "goldDiffAt10": 150, "levelDiffAt10": 0.3},
            "Bot": {"kda": 2.6, "csPerMin": 6.6, "kp": 54, "deaths": 5.4,
                     "csAt10": 80, "visionPerMin": 1.0, "dmgShare": 28},
            "Support": {"kda": 2.6, "csPerMin": 1.2, "kp": 60, "deaths": 5.9,
                         "csAt10": 16, "visionPerMin": 2.4, "wardsPlaced": 18, "controlWards": 2.0},
        },
    },
}


def load_benchmarks(cfg):
    """benchmarks.json（編集可能）を読む。無ければ既定値。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmarks.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_BENCH


def build_payload(records, cfg=None, champ_map=None, champ_tags=None):
    players = []
    unique_ids = set()
    champ_set = set()
    n_players = 0
    for pr in records:
        # 概要サマリーの集計はコーチを除外し、3チームの選手のみで算出する
        if not pr["isCoach"]:
            n_players += 1
            for m in pr["matches"]:
                if m.get("matchId"):
                    unique_ids.add(m["matchId"])
                if m.get("champion"):
                    champ_set.add(m["champion"])
        matches = [{k: m.get(k) for k in MATCH_FIELDS} for m in pr["matches"]]
        players.append({
            "nickname": pr["nickname"],
            "team": pr["team"],
            "role": pr["role"],
            "primaryRole": pr.get("primaryRole", pr["role"]),
            "rolesPlayed": pr.get("rolesPlayed", []),
            "isCoach": pr["isCoach"],
            "agg": pr["agg"],
            "champ_pool": pr["champ_pool"],
            "byRole": pr.get("byRole", {}),
            "matches": matches,
        })
    version = None
    if cfg is not None:
        try:
            import ddragon
            version = ddragon.get_version(cfg)
        except Exception:
            version = None
    return {
        "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "roles": metrics.ROLES,
        "ddragonVersion": version or "15.1.1",
        "players": players,
        "champMap": champ_map or {},
        "champTags": champ_tags or {},
        "rolePriority": ROLE_PRIORITY_METRICS,
        "totals": {
            "n_players": n_players,
            "unique_games": len(unique_ids),
            "n_champs": len(champ_set),
        },
        "benchmarks": load_benchmarks(cfg) if cfg is not None else DEFAULT_BENCH,
    }


def generate(cfg, records, champ_map=None, champ_tags=None):
    payload = build_payload(records, cfg, champ_map, champ_tags)
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    out_path = os.path.join(cfg["output_dir"], "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>初心者大会 戦績分析ダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root{
    --bg:#0e1116; --card:#171c24; --card2:#1d232d; --border:#2a313c;
    --text:#e6e9ef; --muted:#8b95a5; --accent:#5b8def;
    --good:#3fb950; --mid:#c9a23a; --bad:#f0623f;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif;font-size:14px;}
  header{padding:16px 24px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;}
  header h1{margin:0;font-size:18px;}
  header .gen{color:var(--muted);font-size:12px;}
  nav{display:flex;gap:4px;padding:0 16px;border-bottom:1px solid var(--border);background:var(--card);position:sticky;top:0;z-index:20;flex-wrap:wrap;}
  nav button{background:none;border:none;color:var(--muted);padding:13px 18px;font-size:14px;cursor:pointer;border-bottom:2px solid transparent;}
  nav button:hover{color:var(--text);}
  nav button.active{color:var(--text);border-bottom-color:var(--accent);font-weight:600;}
  .page{display:none;padding:20px 24px;max-width:1320px;margin:0 auto;}
  .page.active{display:block;}
  section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin-bottom:20px;}
  section h2{margin:0 0 14px;font-size:15px;}
  section h3{margin:18px 0 10px;font-size:13px;color:var(--muted);}
  .cards{display:flex;gap:12px;flex-wrap:wrap;}
  .stat{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:12px 16px;min-width:120px;flex:1;}
  .stat .n{font-size:24px;font-weight:700;}
  .stat .l{font-size:11px;color:var(--muted);margin-bottom:2px;}
  .stat .sub{font-size:11px;color:var(--muted);margin-top:4px;}
  .stat .up{color:var(--good);} .stat .down{color:var(--bad);}
  .stat-priority{border-color:var(--accent);background:rgba(91,141,239,0.10);}
  table{width:100%;border-collapse:collapse;font-size:13px;}
  th,td{padding:7px 9px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap;}
  th:first-child,td:first-child{text-align:left;}
  th{color:var(--muted);font-weight:600;cursor:pointer;user-select:none;}
  th:hover{color:var(--text);}
  tr:hover td{background:rgba(255,255,255,0.03);}
  .scroll{overflow-x:auto;}
  .clickable{color:var(--accent);cursor:pointer;}
  .clickable:hover{text-decoration:underline;}
  .coach-row td{background:rgba(255,255,255,0.05);font-style:italic;}
  .badge{padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600;}
  .badge.win{background:rgba(63,185,80,0.2);color:var(--good);}
  .badge.lose{background:rgba(240,98,63,0.2);color:var(--bad);}
  select,input[type=text]{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:13px;}
  .controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px;}
  .controls label{font-size:12px;color:var(--muted);}
  .tabs{display:inline-flex;gap:2px;background:var(--card2);border-radius:8px;padding:3px;}
  .tabs button{background:none;border:none;color:var(--muted);padding:6px 12px;border-radius:6px;cursor:pointer;font-size:13px;}
  .tabs button.active{background:var(--accent);color:#fff;}
  .toggle{display:inline-flex;align-items:center;gap:6px;cursor:pointer;}
  .chart-box{position:relative;height:360px;}
  .chart-sm{position:relative;height:300px;}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;}
  .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;}
  .note{font-size:11px;color:var(--muted);margin-top:8px;}
  .pos{color:var(--good);} .neg{color:var(--bad);}
  .pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;margin-right:3px;background:var(--card2);}
  .cicon{width:22px;height:22px;border-radius:5px;vertical-align:middle;margin-right:6px;}
  /* 習熟度マトリクス */
  .profcard{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:12px;}
  .profhead{font-weight:600;margin-bottom:6px;}
  .profrow{display:flex;align-items:center;gap:6px;padding:3px 0;flex-wrap:wrap;min-height:30px;}
  .profrow .lab{width:62px;flex:none;font-size:11px;color:var(--muted);}
  .tier-tok{position:relative;cursor:pointer;}
  .tier-tok img{width:30px;height:30px;border-radius:6px;display:block;}
  .tier-tok .x{position:absolute;top:-4px;right:-4px;background:var(--bad);color:#fff;border-radius:50%;width:14px;height:14px;font-size:10px;line-height:14px;text-align:center;display:none;}
  .tier-tok:hover .x{display:block;}
  .prof-good{box-shadow:0 0 0 2px var(--good);} .prof-norm{box-shadow:0 0 0 2px var(--mid);} .prof-prac{box-shadow:0 0 0 2px var(--muted);}
  .addbox{display:inline-flex;gap:4px;align-items:center;}
  /* ドラフト */
  .draft-cols{display:grid;grid-template-columns:1fr 1.1fr 1fr;gap:16px;}
  .team-col{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:10px;}
  .blue-col{border-top:3px solid #4f8ff7;} .red-col{border-top:3px solid #e5484d;}
  .slot{display:flex;align-items:center;gap:8px;padding:7px 8px;border-bottom:1px solid var(--border);min-height:46px;}
  .slot.cur{background:rgba(91,141,239,0.12);outline:1px solid var(--accent);}
  .slot .role{width:64px;color:var(--muted);font-size:12px;}
  .slot img{width:32px;height:32px;border-radius:6px;}
  .cand{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:7px;cursor:pointer;border:1px solid transparent;}
  .cand:hover{background:rgba(255,255,255,0.05);border-color:var(--border);}
  .cand img{width:30px;height:30px;border-radius:6px;}
  .cand.taken{opacity:0.3;pointer-events:none;}
  .tag{font-size:10px;padding:1px 6px;border-radius:8px;}
  .tag.good{background:rgba(63,185,80,0.2);color:var(--good);} .tag.norm{background:rgba(201,162,58,0.2);color:var(--mid);} .tag.prac{background:rgba(139,149,165,0.2);color:var(--muted);}
  .wl{color:var(--muted);font-size:11px;}
  .kda-sub{color:var(--muted);font-size:11px;}
  table.ugg td,table.ugg th{padding:9px 10px;}
  table.ugg tr:hover td{background:rgba(255,255,255,0.04);}
  @media(max-width:980px){.grid2,.grid3{grid-template-columns:1fr;}}
</style>
</head>
<body>
<header>
  <h1>初心者大会 戦績分析ダッシュボード</h1>
  <span class="gen" id="gen"></span>
</header>
<nav>
  <button data-page="overview" class="active">① 大会全体の概要</button>
  <button data-page="players">② 選手一覧＆比較</button>
  <button data-page="detail">③ 選手詳細</button>
  <button data-page="bench">④ ロール別ベンチマーク</button>
  <button data-page="pool">⑤ チャンピオンプール（習熟度）</button>
  <button data-page="guide">⑥ 使い方ガイド</button>
</nav>

<div class="page active" id="page-overview"></div>
<div class="page" id="page-players"></div>
<div class="page" id="page-detail"></div>
<div class="page" id="page-bench"></div>
<div class="page" id="page-pool"></div>
<div class="page" id="page-guide"></div>

<script>
const DATA = __DATA__;
document.getElementById('gen').textContent = '更新: ' + DATA.generatedAt;

// ===== 共通ヘルパー =====
const ALL = DATA.players;
const PLAYERS = ALL.filter(p=>!p.isCoach);
const COACHES = ALL.filter(p=>p.isCoach);
const ROLES = DATA.roles;
const TEAMS = [...new Set(ALL.map(p=>p.team).filter(Boolean))];
const TEAM_PALETTE = ['#3fb9a8','#d65a8a','#7aa84f','#e0883a','#9b6dde'];
const ROLE_PALETTE = {'Top':'#e0883a','Jungle':'#3fb9a8','Mid':'#5b8def','Bot':'#d65a8a','Support':'#9b6dde'};
// チーム固定カラー: TeamA=赤(自チーム) / TeamB=青 / TeamC=緑
const TEAM_FIXED = {'TeamA':'#e5484d','TeamB':'#4f8ff7','TeamC':'#3fb950'};
const TEAM_COLORS = {}; TEAMS.forEach((t,i)=>TEAM_COLORS[t]=TEAM_FIXED[t]||TEAM_PALETTE[i%TEAM_PALETTE.length]);
const teamColor = t => TEAM_COLORS[t] || '#8b95a5';
const roleColor = r => ROLE_PALETTE[r] || '#5b8def';

Chart.defaults.color = '#8b95a5';
Chart.defaults.font.family = '"Segoe UI","Noto Sans JP",sans-serif';
Chart.defaults.plugins.legend.labels.boxWidth = 12;

// 指標メタ（ラベル・小数桁・高いほど良いか）
const M = {
  winrate:{l:'勝率%',d:1,hi:true}, kda:{l:'KDA',d:2,hi:true}, deaths:{l:'平均デス',d:1,hi:false},
  csPerMin:{l:'CS/min',d:1,hi:true}, csAt10:{l:'CS@10',d:1,hi:true},
  goldDiffAt10:{l:'ゴールド差@10',d:0,hi:true}, levelDiffAt10:{l:'レベル差@10',d:2,hi:true},
  dmgPerMin:{l:'Dmg/min',d:0,hi:true}, dmgShare:{l:'ダメージシェア%',d:1,hi:true},
  dmgDealt:{l:'平均与ダメージ',d:0,hi:true}, dmgTaken:{l:'平均被ダメージ',d:0,hi:false},
  kp:{l:'キル関与率%',d:1,hi:true}, visionPerMin:{l:'視界スコア/min',d:2,hi:true},
  wardsPlaced:{l:'ワード設置/試合',d:1,hi:true}, controlWards:{l:'コントロールW/試合',d:1,hi:true},
  death10:{l:'デス@10',d:2,hi:false},
};
const fmt = (v,d=1)=> v==null?'-':(typeof v==='number'?v.toFixed(d):v);
const VER = DATA.ddragonVersion || '15.1.1';
const champIcon = id => id ? `https://ddragon.leagueoflegends.com/cdn/${VER}/img/champion/${id}.png` : '';
function champCell(name,id){ return id ? `<img class="cicon" src="${champIcon(id)}" onerror="this.style.display='none'">${name||''}` : (name||'-'); }

// role を渡すとそのロール限定の集計、未指定なら通算
function aggVal(p,k,role){ const a=(role && p.byRole && p.byRole[role])?p.byRole[role].agg:p.agg; return a?a[k]:null; }
function playerGames(p,role){ return (role && p.byRole && p.byRole[role])?p.byRole[role].games:(p.agg?p.agg.games:0); }
function playerPool(p,role){ return (role && p.byRole && p.byRole[role])?p.byRole[role].champ_pool:(p.champ_pool||[]); }
// そのロールを実際に担当した選手（team指定でさらに絞り込み可能）
function rolePlayers(role, team){ return PLAYERS.filter(p=>p.byRole && p.byRole[role] && p.byRole[role].games>0 && (!team || p.team===team)); }
// ロール平均（そのロールを担当した選手の、当該ロール集計の平均。team指定でチーム内平均に）
function roleAvg(role,key,team){ const vs=rolePlayers(role,team).map(p=>aggVal(p,key,role)).filter(v=>v!=null); return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null; }
// コーチ平均（role指定時はそのロールを担当したコーチ）※平均は使わず個別表示に移行
function coachAvg(key,role){ const cs=role?COACHES.filter(p=>p.byRole&&p.byRole[role]):COACHES; const vs=cs.map(p=>aggVal(p,key,role)).filter(v=>v!=null); return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null; }
// 個々のコーチ値: そのロールを担当していればロール別、無ければ通算
function coachVal(c,key,role){ if(role && c.byRole && c.byRole[role]) return c.byRole[role].agg[key]; return c.agg?c.agg[key]:null; }
// コーチの主ロール表示用
function coachRoleLabel(c){ return c.primaryRole || c.role || ''; }
// ロール内順位 "x位/N人"
function roleRank(p,key,role){
  const m=M[key]; const peers=rolePlayers(role).map(x=>({n:x.nickname,v:aggVal(x,key,role)})).filter(x=>x.v!=null);
  peers.sort((a,b)=> m.hi ? b.v-a.v : a.v-b.v);
  const idx=peers.findIndex(x=>x.n===p.nickname);
  return idx<0?'-':`${idx+1}位/${peers.length}人`;
}
// ロール相対の条件付き書式色（背景）。role未指定なら全選手で比較。
function condColor(role,key,value){
  if(value==null) return 'transparent';
  const m=M[key]; const peers=role?rolePlayers(role):PLAYERS;
  const vs=peers.map(p=>aggVal(p,key,role)).filter(v=>v!=null).sort((a,b)=>a-b);
  if(vs.length<2) return 'transparent';
  let rank = vs.filter(v=>v<value).length/(vs.length-1); // 0..1（小さい→0）
  let good = m.hi ? rank : 1-rank; // 1=良い
  if(good>=0.75) return 'rgba(63,185,80,0.22)';
  if(good<=0.25) return 'rgba(240,98,63,0.22)';
  return 'transparent';
}
// 0..100 正規化（ロール内 min-max、hi=falseは反転）
function normIn(value, arr, hi){
  const vs=arr.filter(v=>v!=null); if(!vs.length||value==null) return 0;
  const mn=Math.min(...vs), mx=Math.max(...vs); if(mx===mn) return 50;
  let t=(value-mn)/(mx-mn); return Math.round((hi?t:1-t)*100);
}
function clampN(x,a,b){ return Math.max(a,Math.min(b,x)); }
// ロール平均=100 を基準にした相対値（細かいスケールで差が見える）。差分系は加算スケール。
function normRel(value, key, ref){
  if(value==null||ref==null) return 100;
  const m=M[key];
  if(key==='goldDiffAt10') return clampN(100+(value-ref)/15, 20,180);
  if(key==='levelDiffAt10') return clampN(100+(value-ref)*25, 20,180);
  if(ref===0) return 100;
  const r = m.hi ? value/ref : ref/(value||0.001);
  return clampN(r*100, 20, 180);
}
// レーダーの目盛りを実データに合わせて自動調整（100=平均を中心に程よい窓に）
function radarRange(vals){
  const a=vals.filter(v=>v!=null).concat([100]);
  let lo=Math.min(...a), hi=Math.max(...a);
  lo=Math.max(0, Math.floor((lo-8)/10)*10); hi=Math.ceil((hi+8)/10)*10;
  if(hi-lo<40){ const m=(hi+lo)/2; lo=Math.max(0, m-20); hi=m+20; }
  return {min:lo, max:hi, step:Math.max(5, Math.round((hi-lo)/5))};
}
function destroyCharts(ids){ ids.forEach(id=>{ const c=Chart.getChart(id); if(c) c.destroy(); }); }

// ===== ロール別「重要指標」（全員共通＋レーン固有）＝ 自分のロールに関係ない指標の
// 伸びを過大評価しないための重み付けに使う。チャンピオンのアーキタイプ(タグ)が
// 分かる場合は、それに応じた指標もゆるく追加する（レーン×チャンピオンの微調整）。
const ROLE_PRIORITY = DATA.rolePriority || {common:[], byRole:{}};
const CHAMP_TAGS = DATA.champTags || {};   // {championId: ['Tank','Fighter', ...]} (Data Dragon由来、無ければ空)
// タグ別に「この手のチャンピオンなら合わせて見たい指標」をゆるく追加する（控えめな調整）
const TAG_METRIC_BOOST = {
  Support: ['visionPerMin','wardsPlaced','controlWards'],
  Marksman: ['dmgShare','csPerMin'],
  Mage: ['dmgShare'],
  Assassin: ['kda'],
  Tank: [],
  Fighter: [],
};
function champPrimaryTag(champId){ const tags=CHAMP_TAGS[champId]; return (tags && tags.length) ? tags[0] : null; }
// role(＋任意でchampId)の重要指標一覧（重複除去）。opts.forBench=true なら勝率を除く
// （勝率はマッチメイキングで誰でも平均50%に寄るためランク帯比較には使わない）。
function roleMetrics(role, opts, champId){
  const common = ROLE_PRIORITY.common || [];
  const specific = (role && ROLE_PRIORITY.byRole && ROLE_PRIORITY.byRole[role]) || [];
  let list = [...common, ...specific];
  const tag = champId ? champPrimaryTag(champId) : null;
  if(tag && TAG_METRIC_BOOST[tag]) list = list.concat(TAG_METRIC_BOOST[tag]);
  if(opts && opts.forBench) list = list.filter(k=>k!=='winrate');
  return [...new Set(list)].filter(k=>M[k]);
}

// ===== ベンチマーク（ブロンズ〜シルバー）＋ 改善提案 =====
const BENCH = DATA.benchmarks || {};
const BENCH_METRICS = BENCH.metrics || ['kda','csPerMin','kp','deaths'];
const BENCH_TIERS = Object.keys(BENCH.tiers||{});                 // 例: ['Bronze','Silver','Gold']
const TARGET_TIER = BENCH.targetTier || (BENCH_TIERS.indexOf('Silver')>=0?'Silver':BENCH_TIERS[0]) || 'Silver';
// ランク帯×ロール×指標のベンチ値
function benchVal(tier,role,key){ const t=BENCH.tiers&&BENCH.tiers[tier]; const r=t&&t[role]; return (r&&r[key]!=null)?r[key]:null; }
const BENCH_TIPS = {
  csPerMin:'ミニオンのラストヒットを徹底。死なずにレーンに留まりCSを伸ばそう。',
  kda:'デスを抑えつつ関与を増やす。生存して終盤の戦力になる意識を。',
  kp:'マップを見て味方の戦闘へ参加。ロームやオブジェ集合を早めに。',
  deaths:'不要なデスを減らす。引き際を早め、視界の無い場所へ踏み込まない。',
  csAt10:'序盤10分のファームを最優先。無理なロームより安定したCS取得を。',
  death10:'序盤のデスを減らす。レーンで無理せず、ガンク察知の視界を確保。',
  goldDiffAt10:'対面とのCS・ゴールド差を意識。トレードと帰還タイミングを改善。',
  dmgShare:'集団戦の与ダメージを増やす。安全な位置から継続的にダメージを。',
  visionPerMin:'ワード設置・破壊を増やして視界スコアを上げよう。',
  wardsPlaced:'トリンケット/コントロールを切らさず設置する習慣を。',
};
// 改善提案: 目標ランク帯(既定Silver)に未達の指標を、未達度が大きい順に返す
// 指標セットはそのロールの「重要指標」を優先的に使い、ベンチ値が無い指標は
// BENCH_METRICS（従来の共通4指標）で補う。
function suggestions(p, role){
  const out=[];
  const keys = [...new Set([...roleMetrics(role, {forBench:true}), ...BENCH_METRICS])];
  keys.forEach(k=>{ if(!M[k])return; const t=benchVal(TARGET_TIER, role, k), v=aggVal(p,k,role); if(v==null||t==null)return;
    const short = M[k].hi ? (t-v)/(Math.abs(t)||1) : (v-t)/(Math.abs(t)||1);
    if(short>0.02) out.push({k,v,t,short,tip:BENCH_TIPS[k]||''}); });
  out.sort((a,b)=>b.short-a.short); return out;
}

// ===== 日付ユーティリティ（JST基準で試合を日別集計） =====
function toJstDate(ms){ if(ms==null) return null; return new Date(ms + 9*3600*1000).toISOString().slice(0,10); }
function groupByDate(matches){
  const map={};
  matches.forEach(m=>{ const d=toJstDate(m.gameCreation); if(!d) return; (map[d]=map[d]||[]).push(m); });
  return map;
}
function sortedDates(map){ return Object.keys(map).sort(); }
// 直近n個の「試合があった日」を返す（暦日ベース、実際に練習/大会があった日のみをカウント）
function recentActiveDates(matches, n){ return sortedDates(groupByDate(matches)).slice(-n); }
// 選手pがdates(日付文字列の配列)のいずれかに試合をしていればtrue
function playedInDates(p, dates){ return p.matches.some(m=>dates.includes(toJstDate(m.gameCreation))); }

// agg指標キー -> 試合明細(matches[])側のフィールド名（名前が異なるものだけ対応表を持つ）
const MATCH_FIELD_MAP = { kp:'killParticipation', dmgDealt:'dmgToChamp' };
function matchFieldVal(m,k){ return m[MATCH_FIELD_MAP[k]||k]; }
// ある期間（試合の配列）における指標の平均。winrateだけ特別扱い。
function periodAvg(matches,k){
  if(!matches.length) return null;
  if(k==='winrate') return matches.filter(m=>m.win).length/matches.length*100;
  const vs=matches.map(m=>matchFieldVal(m,k)).filter(v=>v!=null);
  return vs.length ? vs.reduce((a,b)=>a+b,0)/vs.length : null;
}

// ===== 「良くなったポイント」：直近N試合 と それ以前 を比較し、伸びた指標を返す =====
const IMPROVE_METRICS = ['winrate','kda','deaths','csPerMin','csAt10','goldDiffAt10','levelDiffAt10','dmgShare','kp','visionPerMin','death10'];
const IMPROVE_MSG = {
  winrate:'勝率が上がっています。今のプレースタイルは合っています。',
  kda:'キル関与を保ちながらデスが減っています。良い判断ができています。',
  deaths:'デスが減りました。無理な戦闘を避けられている証拠です。',
  csPerMin:'CS効率が上がっています。レーン戦の基礎が安定してきました。',
  csAt10:'序盤のファームが伸びています。レーニングの基礎が身についてきました。',
  goldDiffAt10:'序盤のゴールド差が改善しています。対面に勝てる場面が増えています。',
  levelDiffAt10:'序盤のレベル差が改善しています。経験値効率が上がっています。',
  dmgShare:'チーム内の与ダメージシェアが伸びています。集団戦での存在感が増しています。',
  kp:'キル関与率が上がっています。チームの戦闘への関わりが増えています。',
  visionPerMin:'視界スコアが伸びています。マップ把握が上手くなってきました。',
  death10:'序盤のデスが減っています。ガンク対応や視界確保が上達しています。',
};
function improvements(p, role, n){
  n = n || 10;
  const ms = role ? p.matches.filter(m=>m.playedRole===role) : p.matches;
  const total = ms.length;
  if(total < 6) return {list:[], recentN:0, earlierN:0, total};
  const recentN = Math.min(n, Math.floor(total/2));
  const recent = ms.slice(total-recentN);
  const earlier = ms.slice(0, total-recentN);
  // そのロールの重要指標は伸びを1.5倍で評価し、ロールに関係ない指標の伸びが
  // 優先的に上位表示されないようにする（自分のロールに関係ない伸びは影響力が薄いため）。
  const priority = new Set(roleMetrics(role));
  const out=[];
  IMPROVE_METRICS.forEach(k=>{
    if(!M[k]) return;
    const rv=periodAvg(recent,k), ev=periodAvg(earlier,k);
    if(rv==null||ev==null) return;
    const diff=rv-ev;
    const good = M[k].hi ? diff>0 : diff<0;
    if(!good) return;
    const relImprove = Math.abs(diff)/(Math.abs(ev)||1);
    if(relImprove < 0.03) return;   // 3%未満のブレはノイズとして無視
    const isPriority = priority.has(k);
    out.push({k, recent:rv, earlier:ev, diff, relImprove, isPriority, weighted: relImprove*(isPriority?1.5:1)});
  });
  out.sort((a,b)=>b.weighted-a.weighted);
  return {list:out, recentN, earlierN:earlier.length, total};
}

// ===== 自己ベスト更新・連勝/連敗ストリーク（③選手詳細のモチベーション表示） =====
const BEST_CHECKS = [
  {k:'csAt10', label:'CS@10 自己ベスト', hi:true},
  {k:'kda', label:'KDA 自己ベスト', hi:true},
  {k:'goldDiffAt10', label:'ゴールド差@10 自己ベスト', hi:true},
];
function personalBests(ms){
  const out=[];
  if(ms.length<2) return out;
  const last=ms[ms.length-1]; const prev=ms.slice(0,-1);
  BEST_CHECKS.forEach(c=>{
    const v=last[c.k]; if(v==null) return;
    const prevVals=prev.map(m=>m[c.k]).filter(x=>x!=null); if(!prevVals.length) return;
    const best=c.hi?Math.max(...prevVals):Math.min(...prevVals);
    const isBest=c.hi? v>best : v<best;
    if(isBest) out.push({label:c.label, value:v, d:M[c.k].d});
  });
  return out;
}
function streakInfo(ms){
  if(!ms.length) return null;
  const last=ms[ms.length-1].win; let cnt=0;
  for(let i=ms.length-1;i>=0;i--){ if(ms[i].win===last) cnt++; else break; }
  return {win:last, count:cnt};
}

// ===== ナビ =====
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  document.getElementById('page-'+b.dataset.page).classList.add('active');
  RENDER[b.dataset.page]();
});

// =====================================================================
//  ページ1：大会全体の概要
// =====================================================================
let OVSUM={role:'すべて',team:''};
let OVGOOD={role:'すべて',team:''};
let OVCHAMP={role:'全体',team:''};
let OVROLE={team:''};
function ovTeamSelect(id, state, onChange){
  const el=document.getElementById(id);
  el.innerHTML='<option value="">全チーム</option>'+TEAMS.map(t=>`<option value="${t}" ${t===state.team?'selected':''}>${t}</option>`).join('');
  el.onchange=()=>{ state.team=el.value; onChange(); };
}
function ovRoleTabs(id, state, onChange, includeAll){
  const el=document.getElementById(id); el.innerHTML='';
  const opts = includeAll ? ['すべて',...ROLES] : ROLES;
  opts.forEach(r=>{ const b=document.createElement('button'); b.textContent=r; if(r===state.role)b.classList.add('active');
    b.onclick=()=>{ state.role=r; el.querySelectorAll('button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); onChange(); }; el.appendChild(b); });
}
function renderOverview(){
  const el=document.getElementById('page-overview');
  el.innerHTML = `
   <section><h2>サマリー</h2>
     <div class="controls"><label>ロール:</label><div class="tabs" id="ovSumRole"></div>
       <label>チーム:</label><select id="ovSumTeam"></select></div>
     <div class="cards" id="ovSumCards"></div></section>
   <section><h2>日別ハイライト（チーム別）</h2>
     <div id="ovDailyHighlight" style="margin-bottom:10px;font-size:13px"></div>
     <div class="chart-box"><canvas id="ovDailyChart"></canvas></div>
     <div class="note">練習・大会があった日ごとに、TeamA(赤)/TeamB(青)/TeamC(緑)それぞれの勝率を算出。大会が進むにつれて各チームがどう伸びているかの比較に。</div></section>
   <section><h2>今、伸びている選手</h2>
     <div class="controls"><label>ロール:</label><div class="tabs" id="ovGoodRole"></div>
       <label>チーム:</label><select id="ovGoodTeam"></select></div>
     <div id="ovGoodPlay"></div>
     <div class="note">直近2日間の練習日にプレイした選手の中から、直近10試合とそれ以前を比較して最も伸び幅が大きかった選手・指標をピックアップ。コーチが褒めるきっかけに使ってください。</div></section>
   <section><h2>チーム別サマリー</h2>
     <div class="controls"><label>ロール:</label><div class="tabs" id="ovTeamRole"></div></div>
     <div class="scroll"><table id="ovTeam"></table></div>
     <div class="note">行クリックで「選手一覧」をそのチームで絞り込み表示します。</div></section>
   <section><h2>全体 チャンピオン使用回数 ＆ 勝率</h2>
     <div class="controls"><label>ロール:</label><div class="tabs" id="ovChampRole"></div>
       <label>チーム:</label><select id="ovChampTeam"></select></div>
     <div class="chart-box"><canvas id="ovChampChart"></canvas></div></section>
   <section><h2>ロール別 平均指標比較</h2>
     <div class="controls"><label>チーム:</label><select id="ovRoleTeam"></select></div>
     <div class="chart-box"><canvas id="ovRoleChart"></canvas></div>
     <div class="note">どのロールが全体的に課題を抱えているかの把握に。</div></section>`;

  ovRoleTabs('ovSumRole', OVSUM, drawOvSummary, true);
  ovTeamSelect('ovSumTeam', OVSUM, drawOvSummary);
  drawOvSummary();

  ovRoleTabs('ovGoodRole', OVGOOD, drawOvGoodPlay, true);
  ovTeamSelect('ovGoodTeam', OVGOOD, drawOvGoodPlay);
  drawOvGoodPlay();

  let OVTEAMTABLE={role:'すべて'};
  ovRoleTabs('ovTeamRole', OVTEAMTABLE, ()=>drawOvTeamTable(OVTEAMTABLE), true);
  drawOvTeamTable(OVTEAMTABLE);

  ovRoleTabs('ovChampRole', OVCHAMP, drawOvChamp, true);
  // ovChampのロール状態は「全体」表記に合わせる（初期値）
  OVCHAMP.role='全体';
  document.querySelectorAll('#ovChampRole button').forEach(b=>b.classList.toggle('active', b.textContent==='全体'));
  ovTeamSelect('ovChampTeam', OVCHAMP, drawOvChamp);
  drawOvChamp();

  ovTeamSelect('ovRoleTeam', OVROLE, drawOvRole);
  drawOvRole();

  drawOvDaily();
}
function ovFilteredPlayers(role, team){
  let list = PLAYERS;
  if(team) list = list.filter(p=>p.team===team);
  if(role && role!=='すべて') list = list.filter(p=>p.byRole && p.byRole[role] && p.byRole[role].games>0);
  return list;
}
function drawOvSummary(){
  const role = OVSUM.role==='すべて' ? null : OVSUM.role;
  const list = ovFilteredPlayers(OVSUM.role, OVSUM.team);
  const games = list.reduce((s,p)=>s+playerGames(p,role),0);
  let wins=0; const uniqueIds=new Set(); const champSet=new Set();
  list.forEach(p=>{
    const ms = role ? p.matches.filter(m=>m.playedRole===role) : p.matches;
    ms.forEach(m=>{ if(m.win) wins++; if(m.matchId) uniqueIds.add(m.matchId); if(m.champion) champSet.add(m.champion); });
  });
  const avg = key => { const vs=list.map(p=>aggVal(p,key,role)).filter(v=>v!=null); return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:0; };
  const box=document.getElementById('ovSumCards');
  box.innerHTML = `
     <div class="stat"><div class="l">対象選手数</div><div class="n">${list.length}</div></div>
     <div class="stat"><div class="l">試合数(ユニーク)</div><div class="n">${uniqueIds.size}</div><div class="sub">のべ出場 ${games}</div></div>
     <div class="stat"><div class="l">使用チャンプ種</div><div class="n">${champSet.size}</div></div>
     <div class="stat"><div class="l">平均勝率</div><div class="n">${fmt(games?wins/games*100:0,1)}%</div></div>
     <div class="stat"><div class="l">平均KDA</div><div class="n">${fmt(avg('kda'),2)}</div></div>
     <div class="stat"><div class="l">平均CS/min</div><div class="n">${fmt(avg('csPerMin'),1)}</div></div>`;
}
function drawOvTeamTable(state){
  const role = state.role==='すべて' ? null : state.role;
  const tbody = TEAMS.map(t=>{
    const ps=role ? PLAYERS.filter(p=>p.team===t && p.byRole && p.byRole[role] && p.byRole[role].games>0) : PLAYERS.filter(p=>p.team===t);
    const g=ps.reduce((s,p)=>s+playerGames(p,role),0);
    const w=ps.reduce((s,p)=>{ const ms=role?p.matches.filter(m=>m.playedRole===role):p.matches; return s+ms.filter(m=>m.win).length; },0);
    const m=key=>{const vs=ps.map(p=>aggVal(p,key,role)).filter(v=>v!=null);return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null;};
    const wr=g?w/g*100:0;
    const wc = wr>=52?'var(--good)':(wr<48?'var(--bad)':'var(--text)');
    return {t,g,w,wr,wc,kda:m('kda'),cs:m('csPerMin'),gpm:m('goldPerMin')};
  }).sort((a,b)=>b.wr-a.wr);
  let h='<tr><th>チーム</th><th>試合</th><th>勝利</th><th>勝率%</th><th>平均KDA</th><th>CS/min</th><th>G/min</th></tr>';
  tbody.forEach(r=>{ h+=`<tr class="clickable" data-team="${r.t}"><td><span style="color:${teamColor(r.t)}">●</span> ${r.t}</td>`+
    `<td>${r.g}</td><td>${r.w}</td><td style="color:${r.wc};font-weight:600">${fmt(r.wr,1)}</td>`+
    `<td>${fmt(r.kda,2)}</td><td>${fmt(r.cs,1)}</td><td>${fmt(r.gpm,1)}</td></tr>`; });
  const tt=document.getElementById('ovTeam'); tt.innerHTML=h;
  tt.querySelectorAll('tr[data-team]').forEach(tr=>tr.onclick=()=>{ goPlayers(tr.dataset.team); });
}
function drawOvGoodPlay(){
  const box=document.getElementById('ovGoodPlay');
  const allMatches = PLAYERS.flatMap(p=>p.matches);
  const recentDates = recentActiveDates(allMatches, 2);
  if(!recentDates.length){ box.innerHTML='<div class="note">日別データがありません。</div>'; return; }
  let pool = PLAYERS.filter(p=>playedInDates(p, recentDates));
  if(OVGOOD.team) pool = pool.filter(p=>p.team===OVGOOD.team);
  const picks=[];
  pool.forEach(p=>{
    let roles = (p.rolesPlayed&&p.rolesPlayed.length?p.rolesPlayed:[p.primaryRole]);
    if(OVGOOD.role!=='すべて') roles = roles.filter(r=>r===OVGOOD.role);
    roles.forEach(role=>{
      const res=improvements(p, role, 10);
      if(res.list.length) picks.push({p, role, top:res.list[0]});
    });
  });
  const periodNote = `<div class="note" style="margin-bottom:8px">対象期間: ${recentDates.join(' , ')}（直近2日間の練習日にプレイした選手）</div>`;
  if(!picks.length){ box.innerHTML=periodNote+'<div class="note">条件に合う選手の中で、比較に十分な試合数がある人がまだいません。</div>'; return; }
  // ロールの重要指標(weighted)で選手間を比較。無関係な指標の伸びが上位に来ないようにする。
  picks.sort((a,b)=>b.top.weighted-a.top.weighted);
  let h=periodNote+'<div class="cards">';
  picks.slice(0,3).forEach(({p,role,top})=>{
    h+=`<div class="stat" style="border-left:3px solid var(--good)"><div class="l">${p.nickname} <span class="wl">(${p.team} / ${role})</span></div>`+
      `<div class="n" style="font-size:16px">${top.isPriority?'★ ':''}${M[top.k].l} <span class="pos">${top.diff>=0?'+':''}${fmt(top.diff,M[top.k].d)}</span></div>`+
      `<div class="sub">${fmt(top.earlier,M[top.k].d)} → ${fmt(top.recent,M[top.k].d)}</div></div>`;
  });
  h+='</div>';
  box.innerHTML=h;
}
function drawOvDaily(){
  destroyCharts(['ovDailyChart']);
  const perTeam={};
  TEAMS.forEach(t=>{ perTeam[t]=groupByDate(PLAYERS.filter(p=>p.team===t).flatMap(p=>p.matches)); });
  const allDatesSet=new Set();
  TEAMS.forEach(t=>Object.keys(perTeam[t]).forEach(d=>allDatesSet.add(d)));
  const dates=[...allDatesSet].sort();
  const box=document.getElementById('ovDailyHighlight');
  if(!dates.length){ box.innerHTML='<div class="note">日別データがありません。</div>'; return; }
  const datasets = TEAMS.map(t=>{
    const byDate=perTeam[t];
    const data = dates.map(d=> byDate[d] ? (byDate[d].filter(m=>m.win).length/byDate[d].length*100) : null);
    return {label:t+' 勝率%',data,borderColor:teamColor(t),backgroundColor:teamColor(t),tension:0.3,pointRadius:4,spanGaps:false};
  });
  new Chart('ovDailyChart',{type:'line',data:{labels:dates,datasets},options:{responsive:true,maintainAspectRatio:false,
    scales:{y:{beginAtZero:true,max:100,title:{display:true,text:'勝率%'}}},
    plugins:{tooltip:{callbacks:{afterLabel:(c)=>{ const t=TEAMS[c.datasetIndex]; const d=dates[c.dataIndex]; const ms=perTeam[t][d]; return ms?`${ms.length}試合`:'試合なし'; }}}}}});
  // チームごとの直近練習日ハイライト（前回比）
  let msg='';
  TEAMS.forEach(t=>{
    const byDate=perTeam[t]; const ds=sortedDates(byDate);
    if(!ds.length){ msg+=`<div><span style="color:${teamColor(t)};font-weight:600">●${t}</span> データなし</div>`; return; }
    const last=ds[ds.length-1];
    const lastWr=byDate[last].filter(m=>m.win).length/byDate[last].length*100;
    let line=`<span style="color:${teamColor(t)};font-weight:600">●${t}</span> 直近練習日 <b>${last}</b>（${byDate[last].length}試合 / 勝率 ${fmt(lastWr,1)}%）`;
    if(ds.length>=2){
      const prev=ds[ds.length-2];
      const prevWr=byDate[prev].filter(m=>m.win).length/byDate[prev].length*100;
      const d=lastWr-prevWr;
      line+=` <span class="${d>=0?'pos':'neg'}">${d>=0?'▲':'▼'} 前回比 ${d>=0?'+':''}${fmt(d,1)}pt</span>`;
    }
    msg+=`<div style="margin-bottom:4px">${line}</div>`;
  });
  box.innerHTML=msg;
}
function drawOvChamp(){
  destroyCharts(['ovChampChart']);
  const roleFilter = OVCHAMP.role, teamFilter = OVCHAMP.team;
  const pool={};
  PLAYERS.forEach(p=>{
    if(teamFilter && p.team!==teamFilter) return;
    p.matches.forEach(m=>{ const c=m.champion; if(!c)return;
      if(roleFilter!=='全体' && m.playedRole!==roleFilter) return;
      pool[c]=pool[c]||{plays:0,wins:0,byTeam:{},players:{}};
      pool[c].plays++; if(m.win)pool[c].wins++;
      pool[c].byTeam[p.team]=(pool[c].byTeam[p.team]||0)+1;
      pool[c].players[p.nickname]=(pool[c].players[p.nickname]||0)+1; }); });
  let arr=Object.entries(pool).map(([c,v])=>({champ:c,plays:v.plays,winrate:v.wins/v.plays*100,byTeam:v.byTeam,
    top:Object.entries(v.players).sort((a,b)=>b[1]-a[1]).slice(0,3).map(x=>x[0]).join(', ')}));
  arr.sort((a,b)=>b.plays-a.plays); arr=arr.slice(0,20);
  // チーム別の積み上げ棒（どのチームがピックしているか）＋ 勝率の折れ線
  const teamsToShow = teamFilter ? [teamFilter] : TEAMS;
  const teamDs=teamsToShow.map(t=>({type:'bar',label:t,stack:'champ',backgroundColor:teamColor(t),yAxisID:'y',
    data:arr.map(d=>d.byTeam[t]||0)}));
  const lineDs={type:'line',label:'勝率%',data:arr.map(d=>d.winrate),borderColor:'#e6e9ef',
    backgroundColor:'#e6e9ef',yAxisID:'y1',tension:0.3,pointRadius:3};
  new Chart('ovChampChart',{data:{labels:arr.map(d=>d.champ),datasets:[...teamDs,lineDs]},
    options:{responsive:true,maintainAspectRatio:false,
    scales:{y:{stacked:true,position:'left',beginAtZero:true,title:{display:true,text:'使用回数(チーム別)'}},
      y1:{position:'right',beginAtZero:true,max:100,grid:{drawOnChartArea:false},title:{display:true,text:'勝率%'}},
      x:{stacked:true,ticks:{maxRotation:60,minRotation:30}}},
    plugins:{tooltip:{callbacks:{afterLabel:(c)=> c.dataset.type==='line'?('主な使用: '+arr[c.dataIndex].top):''}}}}});
}
function drawOvRole(){
  destroyCharts(['ovRoleChart']);
  const team = OVROLE.team || null;
  const keys=['csPerMin','kda','deaths','wardsPlaced'];
  const ds=keys.map((k,i)=>({label:M[k].l,data:ROLES.map(r=>roleAvg(r,k,team)),
    backgroundColor:['#5b8def','#3fb950','#f0623f','#9b6dde'][i]}));
  new Chart('ovRoleChart',{type:'bar',data:{labels:ROLES,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true}}}});
}

// =====================================================================
//  ページ2：選手一覧＆比較
// =====================================================================
let P2={role:'すべて',team:'',coach:false,expand:false,sort:{k:'winrate',dir:-1}};
function goPlayers(team){ document.querySelector('nav button[data-page="players"]').click(); if(team){P2.team=team;} RENDER.players(); }
function renderPlayers(){
  const el=document.getElementById('page-players');
  el.innerHTML=`
   <section>
     <div class="controls">
       <label>ロール:</label><div class="tabs" id="p2Role"></div>
       <label>チーム:</label><select id="p2Team"></select>
       <label class="toggle"><input type="checkbox" id="p2Coach"> コーチ戦績を含む</label>
       <label class="toggle"><input type="checkbox" id="p2Exp"> 詳細列を表示</label>
     </div>
     <div class="scroll"><table id="p2Table"></table></div>
   </section>
   <section><h2>選手別 勝率比較（ロール連動・チーム色）</h2><div class="chart-box"><canvas id="p2Bar"></canvas></div></section>`;
  // ロールタブ
  const rt=document.getElementById('p2Role');
  ['すべて',...ROLES].forEach(r=>{ const b=document.createElement('button'); b.textContent=r; if(r===P2.role)b.classList.add('active');
    b.onclick=()=>{P2.role=r; rt.querySelectorAll('button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); drawP2();}; rt.appendChild(b); });
  // チーム
  const ts=document.getElementById('p2Team'); ts.innerHTML='<option value="">すべて</option>'+TEAMS.map(t=>`<option ${t===P2.team?'selected':''}>${t}</option>`).join('');
  ts.onchange=()=>{P2.team=ts.value; drawP2();};
  const cb=document.getElementById('p2Coach'); cb.checked=P2.coach; cb.onchange=()=>{P2.coach=cb.checked; drawP2();};
  const ex=document.getElementById('p2Exp'); ex.checked=P2.expand; ex.onchange=()=>{P2.expand=ex.checked; drawP2();};
  drawP2();
}
const P2_BASIC=[['nickname','選手','s'],['team','チーム','s'],['role','ロール','s'],['games','試合','n'],
  ['winrate','勝率%','m'],['kda','KDA','m'],['deaths','平均デス','m'],['csPerMin','CS/min','m'],['top','使用上位','s']];
const P2_DETAIL=[['csAt10','CS@10','m'],['goldDiffAt10','G差@10','m'],['levelDiffAt10','Lv差@10','m'],
  ['dmgPerMin','Dmg/min','m'],['dmgShare','Dmgシェア%','m'],['kp','KP%','m'],['visionPerMin','視界/min','m'],
  ['wardsPlaced','ワード/試合','m'],['controlWards','CtrlW/試合','m']];
function drawP2(){
  const role = P2.role==='すべて' ? null : P2.role;   // 選択ロール（nullなら通算）
  let list;
  if(role){ list = rolePlayers(role).slice(); if(P2.coach) list = list.concat(COACHES.filter(p=>p.byRole&&p.byRole[role])); }
  else { list = (P2.coach ? ALL : PLAYERS).slice(); }
  if(P2.team) list=list.filter(p=>p.team===P2.team);
  const cols = P2.expand ? P2_BASIC.concat(P2_DETAIL) : P2_BASIC;
  const valOf=(p,k)=>{ if(k==='nickname')return p.nickname; if(k==='team')return p.team; if(k==='role')return p.isCoach?'コーチ':(role||p.primaryRole||p.role);
    if(k==='top')return playerPool(p,role).slice(0,3).map(c=>c.champ).join(', '); if(k==='games')return playerGames(p,role); return aggVal(p,k,role); };
  list=[...list].sort((a,b)=>{ const k=P2.sort.k; let va=valOf(a,k),vb=valOf(b,k);
    if(typeof va==='string'){return P2.sort.dir*String(va).localeCompare(String(vb),'ja');}
    va=va==null?-Infinity:va; vb=vb==null?-Infinity:vb; return P2.sort.dir*(va-vb); });
  let h='<tr>'+cols.map(c=>`<th data-k="${c[0]}">${c[1]}${P2.sort.k===c[0]?(P2.sort.dir<0?' ▼':' ▲'):''}</th>`).join('')+'</tr>';
  list.forEach(p=>{
    h+=`<tr class="${p.isCoach?'coach-row':''}">`+cols.map(c=>{
      const k=c[0]; let v=valOf(p,k);
      if(k==='nickname') return `<td><span class="clickable" data-go="${p.nickname}">${v}</span></td>`;
      if(k==='top'){ const pool=playerPool(p,role).slice(0,3);
        return `<td style="text-align:left">${pool.map(c=>`<img class="cicon" style="width:18px;height:18px;margin-right:2px" src="${champIcon(c.champId)}" title="${c.champ}" onerror="this.style.display='none'">`).join('')||'-'}</td>`; }
      if(c[2]==='m'){ const bg=p.isCoach?'transparent':condColor(role,k,v);
        const cls=(k==='goldDiffAt10'||k==='levelDiffAt10')&&v!=null?(v>=0?'pos':'neg'):'';
        return `<td style="background:${bg}" class="${cls}">${fmt(v,M[k]?M[k].d:1)}</td>`; }
      if(c[2]==='n') return `<td>${v==null?'-':v}</td>`;
      return `<td>${v==null?'-':v}</td>`;
    }).join('')+'</tr>';
  });
  const t=document.getElementById('p2Table'); t.innerHTML=h;
  t.querySelectorAll('th').forEach(th=>th.onclick=()=>{ const k=th.dataset.k;
    if(P2.sort.k===k)P2.sort.dir*=-1; else P2.sort={k,dir:(['nickname','team','role','top'].includes(k))?1:-1}; drawP2(); });
  t.querySelectorAll('[data-go]').forEach(s=>s.onclick=()=>openDetail(s.dataset.go));
  // 勝率バー
  destroyCharts(['p2Bar']);
  const bar=list.filter(p=>!p.isCoach);
  new Chart('p2Bar',{type:'bar',data:{labels:bar.map(p=>p.nickname),datasets:[{label:'勝率%',
    data:bar.map(p=>aggVal(p,'winrate',role)),backgroundColor:bar.map(p=>teamColor(p.team))}]},
    options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true,title:{display:true,text:'勝率%'}},x:{ticks:{maxRotation:60,minRotation:30}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:(c)=>`${bar[c.dataIndex].team} / ${role||bar[c.dataIndex].primaryRole}`}}}}});
}

// =====================================================================
//  ページ3：選手詳細
// =====================================================================
let P3={player:null, role:null, growth:'csAt10', coachLine:false, viewMode:'game', improveN:10};
function openDetail(nick){ P3.player=nick; P3.role=null; document.querySelector('nav button[data-page="detail"]').click(); }
function curP(){ return ALL.find(p=>p.nickname===P3.player); }
function ensureRole(){ const p=curP(); const rs=p.rolesPlayed||[]; if(!P3.role || !rs.includes(P3.role)) P3.role = p.primaryRole || rs[0] || p.role; }
function roleMatches(){ const p=curP(); return P3.role ? p.matches.filter(m=>m.playedRole===P3.role) : p.matches; }
function renderDetail(){
  const el=document.getElementById('page-detail');
  if(!P3.player) P3.player=PLAYERS[0].nickname;
  ensureRole();
  el.innerHTML=`
   <section><div class="controls"><label>選手:</label><select id="p3Sel"></select>
     <label>ロール:</label><select id="p3Role"></select></div>
     <div id="p3Profile"></div>
     <div id="p3Badges" style="margin-top:8px"></div></section>
   <section><h2>良くなったポイント <span class="wl">（直近<span id="p3ImproveNLabel"></span>試合 vs それ以前）</span></h2>
     <div class="controls"><label>比較する直近試合数:</label><select id="p3ImproveN"><option value="5">5</option><option value="10">10</option><option value="15">15</option></select></div>
     <div id="p3Improve"></div></section>
   <div class="grid2">
     <section><h2>次に改善したいポイント（${TARGET_TIER}基準）</h2><div id="p3Suggest"></div></section>
     <section><h2>ランク・コーチ比較（主要指標）</h2><div class="scroll"><table id="p3CoachCmp"></table></div>
       <div class="note">選手の主要指標を、ランク帯（Bronze/Silver/Gold）と各コーチの実数値で横並び比較。★=目標ランク(${TARGET_TIER})。
       選手セルは目標ランク以上なら緑・未満なら赤。ランク値は公開統計の目安（近似・<code>benchmarks.json</code>で編集可）。コーチ値はそのロールの戦績、無ければ通算。</div></section>
   </div>
   <section><h2>成長トラッキング ★最重要</h2>
     <div class="controls"><label>指標:</label><select id="p3Growth"></select>
       <label>表示:</label><div class="tabs" id="p3ViewMode"><button data-v="game">試合ごと</button><button data-v="date">日別(平均)</button></div>
       <label class="toggle"><input type="checkbox" id="p3Coach"> コーチ線（各コーチ）</label></div>
     <div class="chart-box"><canvas id="p3GrowthChart"></canvas></div>
     <div class="note">青系の太線=本人の値（選択ロールのみ）。<b>移動平均(5)</b>＝直近5試合の平均で調子のトレンド。
       <b>ロール平均</b>＝同ロールを担当した選手全員の平均（比較の基準）。<b>コーチ平均</b>＝コーチ全員の平均（目標の目安）。
       「日別(平均)」表示にすると、練習した日ごとの平均値の推移で見られます。</div></section>
   <section><h2>デスのタイミング分布</h2><div class="chart-sm"><canvas id="p3Death"></canvas></div>
     <div class="note">横軸=試合内の経過時間(2分刻み) / 縦軸=デス合計。集中する時間帯を発見。</div></section>
   <section><h2>レーニング成績（試合ごと）</h2><div class="scroll"><table id="p3Lane"></table></div></section>
   <section><h2>チャンピオンプール</h2>
     <div class="scroll"><table id="p3Pool" class="ugg"></table></div>
     <div class="chart-sm" style="margin-top:14px"><canvas id="p3PoolChart"></canvas></div></section>
   <section><h2>直近の試合履歴</h2><div class="scroll"><table id="p3Recent"></table></div></section>`;
  const sel=document.getElementById('p3Sel');
  sel.innerHTML=PLAYERS.map(p=>`<option ${p.nickname===P3.player?'selected':''}>${p.nickname}</option>`).join('');
  sel.onchange=()=>{P3.player=sel.value; P3.role=null; ensureRole(); fillRoleSel(); drawP3();};
  fillRoleSel();
  const gs=document.getElementById('p3Growth');
  ['csAt10','deaths','kda','csPerMin','goldDiffAt10','wardsPlaced','dmgShare'].forEach(k=>gs.appendChild(new Option(M[k].l,k)));
  gs.value=P3.growth; gs.onchange=()=>{P3.growth=gs.value; drawGrowth();};
  const cc=document.getElementById('p3Coach'); cc.checked=P3.coachLine; cc.onchange=()=>{P3.coachLine=cc.checked; drawGrowth();};
  const vm=document.getElementById('p3ViewMode');
  vm.querySelectorAll('button').forEach(b=>{ if(b.dataset.v===P3.viewMode)b.classList.add('active');
    b.onclick=()=>{ P3.viewMode=b.dataset.v; vm.querySelectorAll('button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); drawGrowth(); }; });
  const inSel=document.getElementById('p3ImproveN'); inSel.value=String(P3.improveN);
  inSel.onchange=()=>{ P3.improveN=parseInt(inSel.value,10); drawImprovements(); };
  drawP3();
}
function fillRoleSel(){
  const p=curP(); const rs=p.rolesPlayed||[p.role]; const rsel=document.getElementById('p3Role');
  rsel.innerHTML=rs.map(r=>`<option value="${r}" ${r===P3.role?'selected':''}>${r}（${playerGames(p,r)}試合）</option>`).join('');
  rsel.onchange=()=>{P3.role=rsel.value; drawP3();};
}
function drawP3(){ drawProfile(); drawBadges(); drawImprovements(); drawSuggest(); drawCoachCmp(); drawGrowth(); drawDeath(); drawLane(); drawPool(); drawRecent(); }
function drawBadges(){
  const box=document.getElementById('p3Badges'); const ms=roleMatches();
  const streak=streakInfo(ms); const bests=personalBests(ms);
  let h='';
  if(streak && streak.count>=2){
    h+=`<span class="pill" style="background:${streak.win?'rgba(63,185,80,0.2)':'rgba(240,98,63,0.2)'};color:${streak.win?'var(--good)':'var(--bad)'};font-weight:600">`+
      `${streak.win?'🔥 '+streak.count+'連勝中':streak.count+'連敗中・切り替えていこう'}</span> `;
  }
  bests.forEach(b=>{ h+=`<span class="pill" style="background:rgba(63,185,80,0.2);color:var(--good);font-weight:600">🏆 ${b.label}更新！ (${fmt(b.value,b.d)})</span> `; });
  box.innerHTML=h;
}
function drawImprovements(){
  document.getElementById('p3ImproveNLabel').textContent=P3.improveN;
  const p=curP(); const res=improvements(p, P3.role, P3.improveN);
  const box=document.getElementById('p3Improve');
  if(res.total<6){ box.innerHTML='<div class="note">比較に十分な試合数がまだありません（6試合以上でここに表示されます）。まずは試合を重ねていきましょう。</div>'; return; }
  if(!res.list.length){ box.innerHTML='<div class="note">直近の試合で大きく伸びた指標はまだ見当たりません。次の練習で変化が出るか見ていきましょう。</div>'; return; }
  let h=''; res.list.slice(0,3).forEach((s,i)=>{
    const arrow = s.diff>=0?'+':'';
    h+=`<div style="margin-bottom:10px;padding:10px;background:var(--card2);border-left:3px solid var(--good);border-radius:6px">`+
      `<div><b>${i+1}. ${s.isPriority?'★ ':''}${M[s.k].l}</b> <span class="wl">${fmt(s.earlier,M[s.k].d)}</span> → <span class="pos">${fmt(s.recent,M[s.k].d)}</span> `+
      `<span class="pos">(${arrow}${fmt(s.diff,M[s.k].d)})</span></div>`+
      `<div class="note" style="margin-top:4px">${IMPROVE_MSG[s.k]||''}</div></div>`; });
  box.innerHTML=h;
}
function drawSuggest(){
  const p=curP(); const sug=suggestions(p, P3.role);
  const box=document.getElementById('p3Suggest');
  if(!sug.length){ box.innerHTML='<div class="note">主要指標はベンチマークを満たしています。良い状態です。</div>'; return; }
  let h=''; sug.slice(0,3).forEach((s,i)=>{
    h+=`<div style="margin-bottom:10px;padding:10px;background:var(--card2);border-left:3px solid var(--bad);border-radius:6px">`+
       `<div><b>${i+1}. ${M[s.k].l}</b> <span class="neg">現在 ${fmt(s.v,M[s.k].d)}</span> / 目標 ${fmt(s.t,M[s.k].d)}</div>`+
       `<div class="note" style="margin-top:4px">${s.tip}</div></div>`; });
  box.innerHTML=h;
}
function drawCoachCmp(){
  const p=curP(); const role=P3.role;
  // 主要指標を、選手 / ランク帯(Bronze・Silver・Gold) / 各コーチ で横並び比較
  // 指標セットはそのロールの重要指標を優先し、ベンチ値が無いものはBENCH_METRICSで補う。
  const keys = [...new Set([...roleMetrics(role, {forBench:true}), ...BENCH_METRICS])];
  const priority = new Set(roleMetrics(role, {forBench:true}));
  let h='<tr><th>指標</th><th>'+p.nickname+'</th>'+
    BENCH_TIERS.map(t=>`<th>${t}${t===TARGET_TIER?' ★':''}</th>`).join('')+
    COACHES.map(c=>`<th>${c.nickname}<span class="wl"> (${coachRoleLabel(c)})</span></th>`).join('')+'</tr>';
  keys.forEach(k=>{ if(!M[k])return; const v=aggVal(p,k,role); const tgt=benchVal(TARGET_TIER,role,k);
    const better=(v==null||tgt==null)?null:(M[k].hi? v>=tgt : v<=tgt);   // 選手が目標ランク以上か
    const pcol=better==null?'':(better?'var(--good)':'var(--bad)');
    h+=`<tr><td>${priority.has(k)?'★ ':''}${M[k].l}</td><td style="color:${pcol};font-weight:600">${fmt(v,M[k].d)}</td>`+
      BENCH_TIERS.map(t=>`<td class="wl">${fmt(benchVal(t,role,k),M[k].d)}</td>`).join('')+
      COACHES.map(c=>`<td class="wl">${fmt(coachVal(c,k,role),M[k].d)}</td>`).join('')+'</tr>'; });
  document.getElementById('p3CoachCmp').innerHTML=h;
}
// プロフィールカードに出す指標一覧。そのロールの重要指標を先頭に、
// 残りの標準指標(未使用のもの)を後ろに続ける（最大8枚まで）。
function profileCardMetrics(role){
  const priority = roleMetrics(role);
  const extras = ['kda','deaths','csPerMin','csAt10','wardsPlaced'];
  const list = [...priority];
  const seen = new Set(priority);
  extras.forEach(k=>{ if(!seen.has(k) && list.length<8){ seen.add(k); list.push(k); } });
  return list;
}
function drawProfile(){
  const p=curP(); const role=P3.role;
  const priority = new Set(roleMetrics(role));
  const keys = profileCardMetrics(role);
  let h=`<div style="margin-bottom:10px"><b style="font-size:16px">${p.nickname}</b> <span class="pill">${p.team}</span> <span class="pill">${role}</span> <span class="wl">${playerGames(p,role)}試合</span></div>`+
    `<div class="note" style="margin-bottom:8px">★=${role}の重要指標: ${[...priority].map(k=>M[k]?M[k].l:k).join(' / ')}</div><div class="cards">`;
  keys.forEach(k=>{ const m=M[k]; if(!m) return; const v=aggVal(p,k,role); const ra=roleAvg(role,k);
    const better = ra!=null&&v!=null ? (m.hi ? v>=ra : v<=ra) : null;
    const arrow = better==null?'':(better?'<span class="up">▲</span>':'<span class="down">▼</span>');
    const isPriority = priority.has(k);
    h+=`<div class="stat ${isPriority?'stat-priority':''}"><div class="l">${isPriority?'★ ':''}${m.l}</div><div class="n">${fmt(v,m.d)}${k==='winrate'?'%':''}</div>`+
       `<div class="sub">${roleRank(p,k,role)}</div><div class="sub">ロール平均: ${fmt(ra,m.d)} ${arrow}</div></div>`; });
  h+='</div>';
  document.getElementById('p3Profile').innerHTML=h;
}
function movingAvg(arr,w=5){ return arr.map((_,i)=>{ const s=arr.slice(Math.max(0,i-w+1),i+1).filter(v=>v!=null); return s.length?s.reduce((a,b)=>a+b,0)/s.length:null; }); }
function drawGrowth(){
  destroyCharts(['p3GrowthChart']); const p=curP(); const k=P3.growth; const role=P3.role;
  const ms=roleMatches();
  const ra=roleAvg(role,k);
  if(P3.viewMode==='date'){
    const byDate=groupByDate(ms); const dates=sortedDates(byDate);
    const vals=dates.map(d=>periodAvg(byDate[d],k));
    const ds=[{label:M[k].l+'（日別平均）',data:vals,borderColor:teamColor(p.team),backgroundColor:teamColor(p.team),tension:0.2,pointRadius:4,spanGaps:true}];
    if(ra!=null) ds.push({label:'ロール平均',data:dates.map(()=>ra),borderColor:'#3fb950',borderWidth:1.5,pointRadius:0});
    if(P3.coachLine){ const cpal=['#c9a23a','#d67ad6']; COACHES.forEach((c,i)=>{ const cv=coachVal(c,k,role);
      if(cv!=null) ds.push({label:'コーチ:'+c.nickname,data:dates.map(()=>cv),borderColor:cpal[i%cpal.length],borderDash:[6,4],borderWidth:1.5,pointRadius:0}); }); }
    new Chart('p3GrowthChart',{type:'line',data:{labels:dates,datasets:ds},options:{responsive:true,maintainAspectRatio:false,
      scales:{x:{title:{display:true,text:'日付'}},y:{title:{display:true,text:M[k].l}}},
      plugins:{tooltip:{callbacks:{afterLabel:(c)=>{ if(c.datasetIndex!==0)return''; const d=dates[c.dataIndex];
        return `${byDate[d].length}試合`; }}}}}});
    return;
  }
  const vals=ms.map(m=>m[k]);
  const labels=ms.map((m,i)=>i+1);
  const ds=[{label:M[k].l,data:vals,borderColor:teamColor(p.team),backgroundColor:teamColor(p.team),tension:0.2,pointRadius:3,spanGaps:true},
    {label:'移動平均(5)',data:movingAvg(vals),borderColor:'#e6e9ef',borderDash:[4,3],pointRadius:0,tension:0.3,spanGaps:true}];
  if(ra!=null) ds.push({label:'ロール平均',data:labels.map(()=>ra),borderColor:'#3fb950',borderWidth:1.5,pointRadius:0});
  // コーチは平均でなく1人ずつ線を引く
  if(P3.coachLine){ const cpal=['#c9a23a','#d67ad6']; COACHES.forEach((c,i)=>{ const cv=coachVal(c,k,role);
    if(cv!=null) ds.push({label:'コーチ:'+c.nickname,data:labels.map(()=>cv),borderColor:cpal[i%cpal.length],borderDash:[6,4],borderWidth:1.5,pointRadius:0}); }); }
  new Chart('p3GrowthChart',{type:'line',data:{labels,datasets:ds},options:{responsive:true,maintainAspectRatio:false,
    scales:{x:{title:{display:true,text:'試合番号(古い→新しい)'}},y:{title:{display:true,text:M[k].l}}},
    plugins:{tooltip:{callbacks:{afterLabel:(c)=>{ if(c.datasetIndex!==0)return''; const m=ms[c.dataIndex];
      return `${m.win?'WIN':'LOSE'} | ${m.champion} vs ${m.opponentChampion||'?'} | KDA ${m.kills}/${m.deaths}/${m.assists}`; }}}}}});
}
function drawDeath(){
  destroyCharts(['p3Death']); const ms=roleMatches();
  const buckets={}; let maxB=0;
  ms.forEach(m=>(m.deathBuckets||[]).forEach(b=>{buckets[b]=(buckets[b]||0)+1; if(b>maxB)maxB=b;}));
  maxB=Math.max(maxB,15);
  const labels=[],data=[]; for(let b=0;b<=maxB;b++){ labels.push(`${b*2}-${b*2+2}分`); data.push(buckets[b]||0); }
  new Chart('p3Death',{type:'bar',data:{labels,datasets:[{label:'デス数',data,backgroundColor:'#f0623f'}]},
    options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true}},plugins:{legend:{display:false}}}});
}
function drawLane(){
  const rows=[...roleMatches()].reverse();
  let h='<tr><th>試合</th><th>使用</th><th>対面</th><th>勝敗</th><th>CS@10</th><th>G差@10</th><th>Lv差@10</th><th>デス@10</th><th>FB関与</th></tr>';
  rows.forEach((m,i)=>{ const gd=m.goldDiffAt10, ld=m.levelDiffAt10, d10=m.death10;
    h+=`<tr><td>#${rows.length-i}</td><td>${champCell(m.champion,m.championId)}</td><td>${champCell(m.opponentChampion,m.opponentChampionId)}</td>`+
      `<td><span class="badge ${m.win?'win':'lose'}">${m.win?'W':'L'}</span></td><td>${m.csAt10==null?'-':m.csAt10}</td>`+
      `<td class="${gd==null?'':(gd>=0?'pos':'neg')}">${gd==null?'-':(gd>0?'+':'')+gd}</td>`+
      `<td class="${ld==null?'':(ld>=0?'pos':'neg')}">${ld==null?'-':(ld>0?'+':'')+ld}</td>`+
      `<td style="color:${d10==0?'var(--good)':(d10>=2?'var(--bad)':'var(--mid)')}">${d10==null?'-':d10}</td>`+
      `<td>${m.firstBlood==null?'-':(m.firstBlood?'○':'×')}</td></tr>`; });
  document.getElementById('p3Lane').innerHTML=h;
}
function drawPool(){
  const p=curP(); const pool=playerPool(p,P3.role);
  let h='<tr><th>順位</th><th>チャンピオン</th><th>勝率</th><th>KDA</th><th>最大K</th><th>最大D</th><th>CS</th><th>ダメージ</th><th>ゴールド</th></tr>';
  pool.forEach((c,i)=>{ const wc=c.winrate>=52?'var(--good)':(c.winrate<48?'var(--bad)':'var(--text)');
    h+=`<tr><td>${i+1}</td><td style="text-align:left">${champCell(c.champ,c.champId)}</td>`+
      `<td><span style="color:${wc};font-weight:600">${fmt(c.winrate,0)}%</span> <span class="wl">${c.wins}W ${c.losses}L</span></td>`+
      `<td>${fmt(c.kda,2)}<div class="kda-sub">${fmt(c.avgKills,1)}/${fmt(c.avgDeaths,1)}/${fmt(c.avgAssists,1)}</div></td>`+
      `<td>${c.maxKills}</td><td>${c.maxDeaths}</td><td>${c.avgCs}</td><td>${(c.avgDmg||0).toLocaleString()}</td><td>${(c.avgGold||0).toLocaleString()}</td></tr>`; });
  document.getElementById('p3Pool').innerHTML=h;
  destroyCharts(['p3PoolChart']);
  const top=pool.slice(0,12);
  new Chart('p3PoolChart',{data:{labels:top.map(c=>c.champ),datasets:[
    {type:'bar',label:'使用回数',data:top.map(c=>c.plays),backgroundColor:teamColor(p.team),yAxisID:'y'},
    {type:'line',label:'勝率%',data:top.map(c=>c.winrate),borderColor:'#e6e9ef',backgroundColor:'#e6e9ef',yAxisID:'y1',tension:0.3,pointRadius:3}
  ]},options:{responsive:true,maintainAspectRatio:false,scales:{y:{position:'left',beginAtZero:true},
    y1:{position:'right',beginAtZero:true,max:100,grid:{drawOnChartArea:false}},x:{ticks:{maxRotation:60,minRotation:30}}}}});
}
function drawRecent(){
  const rows=[...roleMatches()].reverse().slice(0,30);
  let h='<tr><th>勝敗</th><th>使用</th><th>対面</th><th>K/D/A</th><th>CS(CS/min)</th><th>Dmg</th><th>Gold</th><th>ワード</th><th>CtrlW</th></tr>';
  rows.forEach(m=>{ h+=`<tr><td><span class="badge ${m.win?'win':'lose'}">${m.win?'WIN':'LOSE'}</span></td>`+
    `<td style="text-align:left">${champCell(m.champion,m.championId)}</td><td style="text-align:left">${champCell(m.opponentChampion,m.opponentChampionId)}</td><td>${m.kills}/${m.deaths}/${m.assists}</td>`+
    `<td>${m.totalCs} (${fmt(m.csPerMin,1)})</td><td>${(m.dmgToChamp||0).toLocaleString()}</td><td>${(m.goldEarned||0).toLocaleString()}</td>`+
    `<td>${m.wardsPlaced}</td><td>${m.controlWards}</td></tr>`; });
  document.getElementById('p3Recent').innerHTML=h;
}

// =====================================================================
//  ページ4：ロール別ベンチマーク
// =====================================================================
let P4={role:'Top', coach:false, x:'goldDiffAt10', y:'winrate'};
function renderBench(){
  const el=document.getElementById('page-bench');
  el.innerHTML=`
   <section><div class="controls"><label>ロール:</label><div class="tabs" id="p4Role"></div></div></section>
   <section><h2>コーチ比較（実数値）</h2><div class="scroll"><table id="p4CoachTable"></table></div>
     <div class="note">ロール内の各選手とコーチを実数値で比較。下部の行が各コーチ（参考値）。</div></section>
   <section><h2>指標別ランキング</h2><div class="grid3" id="p4Ranks"></div></section>`;
  const rt=document.getElementById('p4Role');
  ROLES.forEach(r=>{ const b=document.createElement('button'); b.textContent=r; if(r===P4.role)b.classList.add('active');
    b.onclick=()=>{P4.role=r; rt.querySelectorAll('button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); drawP4();}; rt.appendChild(b); });
  drawP4();
}
function drawP4(){ drawP4CoachTable(); drawP4Ranks(); }
function drawP4CoachTable(){
  const role=P4.role; const ps=rolePlayers(role);
  const keys=['winrate','kda','csPerMin','csAt10','deaths','kp','dmgShare','dmgDealt','dmgTaken','visionPerMin','wardsPlaced'];
  let h='<tr><th>選手</th>'+keys.map(k=>`<th>${M[k].l}</th>`).join('')+'</tr>';
  ps.forEach(p=>{ h+=`<tr><td>${p.nickname}</td>`+keys.map(k=>`<td>${fmt(aggVal(p,k,role),M[k].d)}</td>`).join('')+'</tr>'; });
  // コーチは平均でなく1人ずつ行で表示（そのロールの戦績、無ければ通算）
  COACHES.forEach(c=>{ const onRole = c.byRole && c.byRole[role];
    h+=`<tr class="coach-row"><td>${c.nickname}<span class="wl"> (C・${coachRoleLabel(c)}${onRole?'':'/通算'})</span></td>`+
      keys.map(k=>`<td>${fmt(coachVal(c,k,role),M[k].d)}</td>`).join('')+'</tr>'; });
  document.getElementById('p4CoachTable').innerHTML=h;
}
function drawP4Ranks(){
  const cont=document.getElementById('p4Ranks'); cont.innerHTML='';
  const keys=['csPerMin','kda','deaths','wardsPlaced','dmgShare','dmgDealt','dmgTaken']; const role=P4.role;
  const ps=rolePlayers(role);
  keys.forEach(k=>{ const div=document.createElement('div'); div.innerHTML=`<h3>${M[k].l}${M[k].hi?'':'（少ない順）'}</h3><div class="chart-sm"><canvas id="rk_${k}"></canvas></div>`; cont.appendChild(div);
    const arr=[...ps].map(p=>({n:p.nickname,v:aggVal(p,k,role),t:p.team})).filter(x=>x.v!=null).sort((a,b)=>M[k].hi?b.v-a.v:a.v-b.v);
    setTimeout(()=>new Chart('rk_'+k,{type:'bar',data:{labels:arr.map(x=>x.n),datasets:[{data:arr.map(x=>x.v),backgroundColor:arr.map(x=>teamColor(x.t))}]},
      options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{beginAtZero:true}}}}),0);
  });
}
function drawP4Scatter(){
  destroyCharts(['p4Scatter']); const role=P4.role; const ps=rolePlayers(role);
  const pts=ps.map(p=>({x:aggVal(p,P4.x,role),y:aggVal(p,P4.y,role),n:p.nickname})).filter(d=>d.x!=null&&d.y!=null);
  new Chart('p4Scatter',{type:'scatter',data:{datasets:[{label:P4.role,data:pts,backgroundColor:roleColor(P4.role),pointRadius:6,pointHoverRadius:9}]},
    options:{responsive:true,maintainAspectRatio:false,scales:{x:{title:{display:true,text:M[P4.x].l}},y:{title:{display:true,text:M[P4.y].l}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:(c)=>`${c.raw.n}: (${fmt(c.raw.x,M[P4.x].d)}, ${fmt(c.raw.y,M[P4.y].d)})`}}}}});
}

// ===== 初期描画 =====
// =====================================================================
//  ⑤ チャンピオンプール（習熟度マトリクス）  SHGアナリストレポート風
// =====================================================================
const ROLE_ORDER=['Top','Jungle','Mid','Bot','Support'];
function teamPlayers(team){ return PLAYERS.filter(p=>p.team===team).sort((a,b)=>ROLE_ORDER.indexOf(a.primaryRole)-ROLE_ORDER.indexOf(b.primaryRole)); }
function lsGet(k){ try{return localStorage.getItem(k);}catch(e){return null;} }
function lsSet(k,v){ try{localStorage.setItem(k,v);}catch(e){} }
function profKey(nick,id){ return 'prof:'+nick+':'+id; }
function autoTier(c){ if(c.plays>=5) return '得意'; if(c.plays>=2) return '普通'; return '練習中'; }
function profPool(p, role){
  if(p.isCoach){ if(role && p.byRole && p.byRole[role]) return p.byRole[role].champ_pool; return p.champ_pool||[]; }
  return (p.byRole && p.primaryRole && p.byRole[p.primaryRole]) ? p.byRole[p.primaryRole].champ_pool : (p.champ_pool||[]);
}
function teamCoaches(team){ return COACHES.filter(p=>p.team===team); }
// Data Dragonのタグを日本語に（レーン×チャンピオンの参考表示用。取得できない場合は表示しない）
const TAG_JA = {Fighter:'ファイター', Tank:'タンク', Mage:'メイジ', Assassin:'アサシン', Marksman:'マークスマン', Support:'サポート'};
function champStatsTable(pool){
  if(!pool||!pool.length) return '<div class="wl" style="padding:4px 0">データなし</div>';
  const hasTags = Object.keys(CHAMP_TAGS).length>0;
  let h='<table class="ugg" style="margin-top:6px;font-size:12px"><tr><th>チャンプ</th>'+(hasTags?'<th>タイプ</th>':'')+'<th>使用</th><th>勝率</th><th>KDA</th><th>CS/min</th><th>平均Dmg</th></tr>';
  pool.forEach(c=>{ const wc=c.winrate>=52?'var(--good)':(c.winrate<48?'var(--bad)':'var(--text)');
    const tag = champPrimaryTag(c.champId); const tagCell = hasTags?`<td class="wl">${tag?(TAG_JA[tag]||tag):'-'}</td>`:'';
    h+=`<tr><td style="text-align:left">${champCell(c.champ,c.champId)}</td>${tagCell}<td>${c.plays}</td><td style="color:${wc}">${fmt(c.winrate,0)}% <span class="wl">${c.wins}W${c.losses}L</span></td><td>${fmt(c.kda,2)}</td><td>${fmt(c.csPerMin,1)}</td><td>${(c.avgDmg||0).toLocaleString()}</td></tr>`; });
  return h+'</table>';
}
function nameToId(name){ const e=Object.entries(DATA.champMap||{}).find(([id,n])=>n===name||id===name); return e?e[0]:null; }
function getProfMap(p, role){
  const map={};
  profPool(p, role).forEach(c=>{ if(c.champId) map[c.champId]={champ:c.champ,plays:c.plays,winrate:c.winrate,tier:autoTier(c)}; });
  let added=[]; try{ added=JSON.parse(lsGet('profadd:'+p.nickname)||'[]'); }catch(e){}
  // 手動追加分は、実在するチャンピオンID(DATA.champMapに存在)のみ反映する。
  // 過去の不具合や誤操作でブラウザのlocalStorageに紛れ込んだ無効なID（例: "Strawberry_xxx"）はここで除外される。
  added.forEach(a=>{ if(!DATA.champMap || !DATA.champMap[a.id]) return; if(!map[a.id]) map[a.id]={champ:a.name,plays:0,winrate:null,tier:'練習中'}; });
  Object.keys(map).forEach(id=>{ const ov=lsGet(profKey(p.nickname,id)); if(ov && ov!=='除外') map[id].tier=ov; if(ov==='除外') delete map[id]; });
  return map;
}
function cycleProf(nick,id,role){ const p=ALL.find(x=>x.nickname===nick); const map=getProfMap(p, role||null); const cur=map[id]?map[id].tier:'練習中'; const order=['得意','普通','練習中']; lsSet(profKey(nick,id), order[(order.indexOf(cur)+1)%3]); }
let POOLTEAM=null;
const POOLCOACHROLE={};   // コーチ別の表示ロール（''=全ロール）
function renderPool(){
  const el=document.getElementById('page-pool');
  if(!POOLTEAM) POOLTEAM=TEAMS[0];
  el.innerHTML=`<section><div class="controls"><label>チーム:</label><div class="tabs" id="poolTeam"></div></div>
    <div class="note">アイコンをクリックで <b>得意→普通→練習中</b> を切替／右上の×で除外／「追加」で任意のチャンプを練習中に追加。変更はこのブラウザに保存されます（自動分類: 5戦以上=得意, 2〜4戦=普通, 1戦=練習中）。</div>
    <div id="poolBody" style="margin-top:12px"></div></section>`;
  const tt=document.getElementById('poolTeam');
  TEAMS.forEach(t=>{ const b=document.createElement('button'); b.textContent=t; if(t===POOLTEAM)b.classList.add('active');
    b.onclick=()=>{POOLTEAM=t; tt.querySelectorAll('button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); drawPool2();}; tt.appendChild(b); });
  drawPool2();
}
function poolCard(p, roleLabel){
  const crole = p.isCoach ? (POOLCOACHROLE[p.nickname]||'') : '';   // ''=全ロール
  const pool = profPool(p, crole||null);
  const map=getProfMap(p, crole||null); const byTier={'得意':[],'普通':[],'練習中':[]};
  Object.entries(map).forEach(([id,c])=>{ if(byTier[c.tier]) byTier[c.tier].push({id,...c}); });
  for(const t in byTier) byTier[t].sort((a,b)=>b.plays-a.plays);
  const headGames = (p.isCoach && crole && p.byRole[crole]) ? p.byRole[crole].games : p.agg.games;
  let h=`<div class="profcard"><div class="profhead">${roleLabel} ・ ${p.nickname} <span class="wl">${headGames}試合</span></div>`;
  // コーチはポジションで絞り込めるタブを表示（チャンピオンが多すぎる対策）
  if(p.isCoach){
    const roles=p.rolesPlayed||[];
    h+=`<div class="profrow"><span class="lab">ポジション</span><div class="tabs">`+
      [['','全']].concat(roles.map(r=>[r,r])).map(([val,lab])=>`<button class="cfilt ${val===crole?'active':''}" data-coach="${p.nickname}" data-crole="${val}">${lab}${val&&p.byRole[val]?`(${p.byRole[val].games})`:''}</button>`).join('')+`</div></div>`;
  }
  ['得意','普通','練習中'].forEach(tier=>{ const cls=tier==='得意'?'prof-good':(tier==='普通'?'prof-norm':'prof-prac');
    h+=`<div class="profrow"><span class="lab">${tier}</span>`+
      byTier[tier].map(c=>`<span class="tier-tok" data-p="${p.nickname}" data-id="${c.id}" data-role="${crole}" title="${c.champ}${c.plays?(' '+c.plays+'戦'):''}"><img class="${cls}" src="${champIcon(c.id)}" onerror="this.style.display='none'"><span class="x" data-x="1">×</span></span>`).join('')+
      `</div>`; });
  h+=`<div class="profrow"><span class="lab">追加</span><span class="addbox"><input type="text" list="champlist" id="add_${p.nickname}" placeholder="チャンプ名"><button data-add="${p.nickname}">追加</button></span></div>`;
  h+=`<details open style="margin-top:6px"><summary class="wl" style="cursor:pointer">チャンピオン別戦績（${pool.length}種・使用回数/勝率）</summary>${champStatsTable(pool)}</details>`;
  return h+'</div>';
}
function drawPool2(){
  const body=document.getElementById('poolBody'); let h='';
  teamPlayers(POOLTEAM).forEach(p=>{ h+=poolCard(p, p.primaryRole); });
  const cs=teamCoaches(POOLTEAM);
  if(cs.length){ h+=`<div class="profhead" style="margin:16px 0 6px;color:var(--muted)">― コーチ（おまけ：チャンピオンプール／戦績）―</div>`;
    cs.forEach(c=>{ h+=poolCard(c, 'コーチ/'+(c.primaryRole||'')); }); }
  h+=`<datalist id="champlist">${Object.values(DATA.champMap||{}).map(n=>`<option value="${n}">`).join('')}</datalist>`;
  body.innerHTML=h;
  body.querySelectorAll('.tier-tok').forEach(tok=>{ tok.onclick=(e)=>{ const nick=tok.dataset.p,id=tok.dataset.id,role=tok.dataset.role||null;
    if(e.target.dataset.x){ lsSet(profKey(nick,id),'除外'); } else { cycleProf(nick,id,role); } drawPool2(); }; });
  body.querySelectorAll('.cfilt').forEach(b=>{ b.onclick=()=>{ POOLCOACHROLE[b.dataset.coach]=b.dataset.crole; drawPool2(); }; });
  body.querySelectorAll('[data-add]').forEach(btn=>{ btn.onclick=()=>{ const nick=btn.dataset.add; const inp=document.getElementById('add_'+nick); const id=nameToId((inp.value||'').trim()); if(!id)return;
    let added=[]; try{added=JSON.parse(lsGet('profadd:'+nick)||'[]');}catch(e){} if(!added.find(a=>a.id===id)){added.push({id,name:DATA.champMap[id]||id}); lsSet('profadd:'+nick,JSON.stringify(added));} lsSet(profKey(nick,id),'練習中'); drawPool2(); }; });
}

// =====================================================================
//  ページ6：使い方ガイド
// =====================================================================
const GUIDE_METRIC_DESC = {
  winrate:'勝った試合の割合。',
  kda:'(キル+アシスト)÷デス。数字が大きいほど「戦闘で活躍しつつ生き残っている」目安。',
  deaths:'1試合あたりの平均デス数。少ないほど良い。',
  csPerMin:'1分あたりのミニオン処理数。レーンでの資源獲得力の目安。',
  csAt10:'試合開始10分時点のCS(ミニオン処理数)。序盤のファーム力の目安。',
  goldDiffAt10:'10分時点の、対面（同じロールの相手）とのゴールド差。プラスならリード。',
  levelDiffAt10:'10分時点の、対面とのレベル差。',
  dmgPerMin:'1分あたりの与ダメージ（対チャンピオン）。',
  dmgShare:'チーム全体の与ダメージのうち、自分が占めた割合。',
  dmgDealt:'1試合あたりの平均与ダメージ（対チャンピオン）。',
  dmgTaken:'1試合あたりの平均被ダメージ。タンク役などは高くなりやすい。',
  kp:'キル関与率。チームのキルのうち、自分がキル or アシストで関わった割合。',
  visionPerMin:'1分あたりの視界スコア。マップ把握への貢献度の目安。',
  wardsPlaced:'1試合あたりのワード設置数。',
  controlWards:'1試合あたりのコントロールワード購入・設置数。',
  death10:'10分時点までのデス数。序盤の被弾（ガンク等）の目安。',
};
function renderGuide(){
  const el=document.getElementById('page-guide');
  const metricRows = Object.keys(M).map(k=>{
    const d = GUIDE_METRIC_DESC[k] || '';
    return `<tr><td>${M[k].l}</td><td style="text-align:left">${d}</td></tr>`;
  }).join('');
  el.innerHTML = `
  <section><h2>このダッシュボードについて</h2>
    <p>初心者大会に参加する選手・コーチ向けの戦績分析ツールです。Riot Games の公式データ（Riot API）をもとに、
    各選手の試合結果を自動集計して表示しています。<b>「弱点探し」だけでなく、良くなった点も一緒に確認して、
    次の練習のモチベーションにしてもらうこと</b>を目的にしています。</p>
    <p class="note">対象: ${PLAYERS.length}選手 / コーチ${COACHES.length}名 / 総試合数 ${DATA.totals ? DATA.totals.unique_games : '-'} / 最終更新 ${DATA.generatedAt}</p>
  </section>

  <section><h2>各ページの見方</h2>
    <table><tr><th>ページ</th><th style="text-align:left">内容</th></tr>
    <tr><td class="clickable" data-goto="overview">① 大会全体の概要</td><td style="text-align:left">全選手・チームの総合サマリー。<b>日別ハイライト</b>と<b>今、伸びている選手</b>で全体の成長を確認できます。ロール・チームで絞り込み可能。</td></tr>
    <tr><td class="clickable" data-goto="players">② 選手一覧＆比較</td><td style="text-align:left">同じロール同士で戦績を横並び比較。緑=上位／赤=下位の色分けで一目で分かる。</td></tr>
    <tr><td class="clickable" data-goto="detail">③ 選手詳細</td><td style="text-align:left"><b>指導の核となるページ。</b>まず<b>良くなったポイント</b>と自己ベスト/連勝バッジで成長を確認し、
      その後で改善したいポイントや成長トラッキング（試合ごと/日別）、デスの多い時間帯、チャンピオンプール、直近の試合履歴を見られます。選手名クリックでもここに来られます。</td></tr>
    <tr><td class="clickable" data-goto="bench">④ ロール別ベンチマーク</td><td style="text-align:left">同ロール内での実数値ランキングと、コーチとの比較表。</td></tr>
    <tr><td class="clickable" data-goto="pool">⑤ チャンピオンプール（習熟度）</td><td style="text-align:left">選手ごとの得意・普通・練習中チャンピオンを一覧表示。アイコンをクリックすると習熟度を切替できます（下記参照）。</td></tr>
    </table>
  </section>

  <section><h2>「良くなったポイント」の見方（③選手詳細）</h2>
    <p>直近の試合（既定10試合、5/15にも変更可）と、それより前の試合を比較して、<b>伸びている指標</b>を上位3つ表示します。
    数字が「悪かった頃→良くなった今」の形で並ぶので、練習の成果を実感しやすくなっています。
    十分な試合数（6試合以上）が無い場合や、まだ大きな伸びが見えない場合はその旨を表示します。</p>
    <p class="note">①の「今、伸びている選手」は、直近2日間の練習日にプレイした選手の中から、最も伸び幅が大きかった人をピックアップしたものです。ロール・チームで絞り込みも可能。コーチが練習の最後に一言褒める際のヒントにどうぞ。</p>
  </section>

  <section><h2>★ ロールごとの「重要指標」について</h2>
    <p>ロールによって重視すべき指標は異なるため、各レーンの★重要指標を以下のとおり設定しています。
    ③選手詳細のプロフィールカードで★マークが付いている指標がそれにあたり、「良くなったポイント」「今、伸びている選手」
    「次に改善したいポイント」でも、自分のロールに関係ない指標の伸び・提案が優先的に出ないよう重み付けしています。</p>
    <table><tr><th>ロール</th><th style="text-align:left">重要指標</th></tr>
    <tr><td>全ロール共通</td><td style="text-align:left">勝率 / CS@10 / 視界スコア/min</td></tr>
    <tr><td>Top・Mid</td><td style="text-align:left">（共通に加えて）ゴールド差@10 / レベル差@10</td></tr>
    <tr><td>Jungle</td><td style="text-align:left">（共通に加えて）キル関与率 / 平均デス</td></tr>
    <tr><td>Bot</td><td style="text-align:left">（共通に加えて）CS/min / 平均デス / ダメージシェア</td></tr>
    <tr><td>Support</td><td style="text-align:left">（共通に加えて）キル関与率 / ワード設置/試合 / コントロールW/試合</td></tr>
    </table>
    <p class="note">チャンピオンプール（⑤・③）にはチャンピオンの「タイプ」（サポート/タンク/マークスマン等）も表示され、
    レーン内でもチャンピオンによって役割が異なることの参考にできます（Data Dragonから取得。オフライン環境等で取得できない場合は非表示）。
    ロールやチャンピオンによる重視指標の設定は<code>dashboard.py</code>の<code>ROLE_PRIORITY_METRICS</code>で調整できます。</p>
  </section>

  <section><h2>⑤ 習熟度アイコンの操作方法</h2>
    <p>⑤ページのチャンピオンアイコンは、<b>クリックするたびに 得意→普通→練習中 と切り替わります</b>。
    アイコン右上に出る「×」をクリックするとそのチャンプを一覧から除外できます。
    使ったことのないチャンピオンを追加したい場合は、選手名の横の入力欄にチャンピオン名を入力して追加してください。</p>
    <p class="note">この変更は<b>あなたが今見ているブラウザにのみ保存</b>されます（localStorage）。他の人の画面には反映されません。
    最初は戦績（5戦以上=得意 / 2〜4戦=普通 / 1戦=練習中）から自動で分類されています。</p>
  </section>

  <section><h2>指標の意味（用語集）</h2>
    <div class="scroll"><table><tr><th>指標</th><th style="text-align:left">意味</th></tr>${metricRows}</table></div>
    <p class="note">「@10」が付く指標は試合開始10分時点の値、「ロール平均」は同じロールを担当した選手全員の平均、
    「移動平均」は直近5試合の平均（調子のトレンドを見るための線）です。</p>
  </section>

  <section><h2>よくある質問（Q&A）</h2>
    <p><b>Q. 自分の試合が反映されていません</b><br>A. データの更新は運営（コーチ）が手動で行っています。最新の試合が反映されるまで少し時間がかかることがあります。</p>
    <p><b>Q. 数字が想定より少ないです</b><br>A. このダッシュボードは<b>自分の指定ロール（担当レーン）で担当した試合のみ</b>を集計しています。
    別のロールで遊んだ試合、対AI（Co-op vs AI）の試合、ARAM/アリーナ/スワーム等の特殊モードの試合は含まれません
    （ノーマル・スイフトプレイ・ランクのサモナーズリフト対戦のみを集計対象としています）。</p>
    <p><b>Q. CS@10などが空欄です</b><br>A. その試合の詳細データ（タイムライン）がまだ取得されていない可能性があります。次回更新で反映されます。</p>
    <p><b>Q. ランク帯の基準値はどこから来ていますか？</b><br>A. 公開されている統計の近似値です。目安として使ってください（完全に正確な値ではありません）。</p>
    <p><b>Q. 「良くなったポイント」に何も出ません</b><br>A. まだ試合数が少ない（6試合未満）か、直近で大きな伸びが無い状態です。試合を重ねるうちに表示されるようになります。</p>
  </section>
  `;
  el.querySelectorAll('[data-goto]').forEach(t=>{ t.onclick=()=>{ document.querySelector(`nav button[data-page="${t.dataset.goto}"]`).click(); }; });
}

const RENDER={overview:renderOverview,players:renderPlayers,detail:renderDetail,bench:renderBench,pool:renderPool,guide:renderGuide};
renderOverview();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import common
    import analyze
    analyze.main()
