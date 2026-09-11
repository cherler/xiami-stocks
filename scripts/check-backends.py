"""两个后端跑同一批只读接口，逐字节比对返回。

**为什么不是"PG 那边不报错就算过"。** 不报错的 SQL 照样能返回错的东西：
排序少了决胜键、NULL 排到了另一头、GROUP BY 挑了另一行。这一轮就是这么
抓到首页公告列表在两个后端显示不同 8 条的——两边都是 200，都"正常"。
同一份数据、同一个接口，结果就该一模一样，那就逐字节比。

跑之前先让两边数据一致：
    python scripts/migrate_to_pg.py --replace
再分别起服务：
    uvicorn stock_decision.main:app --app-dir apps/api --port 8108                    # SQLite
    STOCK_DB_BACKEND=postgres uvicorn stock_decision.main:app --app-dir apps/api --port 8109
然后跑这个脚本。

/api/v1/local-data 天生不同（一个报文件路径、一个报库与 schema），已在白名单里。
"""
import json
import sys
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

READ_ONLY = [
    "/health",
    "/api/v1/dashboard",
    "/api/v1/companies",
    "/api/v1/companies/groups",
    "/api/v1/companies/export",
    "/api/v1/portfolios",
    "/api/v1/data-providers",
    "/api/v1/local-data",
    "/api/v1/inbox?relevance=高&limit=20",
    "/api/v1/inbox?limit=20",
    "/api/v1/news?limit=20",
    "/api/v1/news/feeds",
    "/api/v1/reports",
    "/api/v1/methods",
    "/api/v1/sync/jobs",
    "/api/v1/sync/runs",
    "/api/v1/reviews/queue",
    "/api/v1/reviews/attribution",
    "/api/v1/industries",
    "/api/v1/industries/comparison",
    "/api/v1/universe/summary",
    "/api/v1/universe/sample",
    "/api/v1/screen/strategies",
    "/api/v1/screen/runs",
    "/api/v1/screen/fields",
    "/api/v1/heatmap",
    "/api/v1/heatmap?scope=行业&metric=change_percent",
    "/api/v1/briefing",
    "/api/v1/tasks",
    "/api/v1/companies/1",
    "/api/v1/companies/2",
    "/api/v1/companies/1/supply-chain",
    "/api/v1/companies/1/revisions",
    "/api/v1/universe/percentile?symbol=600519",
    "/api/v1/backups",
]


def get(port, path):
    from urllib.parse import quote
    # 中文查询参数要编码，否则 urllib 直接抛 ascii 编码错误（上一版把这个当成了接口失败）
    path = quote(path, safe="/?&=%")
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=60) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return 0, f"__ERR__ {e}"


# 两个后端各自跑着自己的调度器，启动时各刷一次行情——于是所有「上次同步于」
# 差十几秒。那不是方言翻译的问题，归一掉，剩下的差异才是真的。
TIME_KEYS = {
    "database", "database_path", "database_size", "generated_at", "as_of_wall",
    "age_hours", "last_attempt_at", "last_success_at", "last_finished_at",
    "last_started_at", "started_at", "finished_at", "updated_at",
    "market_timestamp", "refreshed_at", "quote_as_of", "price_as_of", "next_run_at",
}


def normalise(text):
    """去掉两边天然不同的部分：数据库位置、各自调度器留下的时间戳。"""
    try:
        data = json.loads(text)
    except Exception:
        return text
    def walk(node):
        if isinstance(node, dict):
            return {k: ("<变化>" if k in TIME_KEYS else walk(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return json.dumps(walk(data), ensure_ascii=False, sort_keys=True)


same = diff = err = 0
for path in READ_ONLY:
    s1, b1 = get(8108, path)
    s2, b2 = get(8109, path)
    if s1 != s2:
        print(f"  ❌ {path}\n       状态码 SQLite={s1} PG={s2}\n       PG: {b2[:200]}")
        err += 1
        continue
    if b1.startswith("__ERR__") or b2.startswith("__ERR__"):
        print(f"  ❌ {path}  连接失败 {b1[:80]} / {b2[:80]}")
        err += 1
        continue
    n1, n2 = normalise(b1), normalise(b2)
    if path.startswith("/api/v1/local-data"):
        # 这个接口本来就该不同：SQLite 报文件路径与文件大小，PG 报库与 schema。
        print(f"  ➖ {path}  两边本就不同（数据库位置），跳过")
        same += 1
        continue
    if n1 == n2:
        print(f"  ✅ {path}  ({len(b1)} 字节, {s1})")
        same += 1
    else:
        print(f"  ⚠️  {path}  返回不同")
        for i in range(min(len(n1), len(n2))):
            if n1[i] != n2[i]:
                print(f"       首个差异在第 {i} 字节")
                print(f"       SQLite …{n1[max(0,i-90):i+90]}…")
                print(f"       PG     …{n2[max(0,i-90):i+90]}…")
                break
        else:
            print(f"       长度不同：SQLite {len(n1)} / PG {len(n2)}")
        diff += 1

print(f"\n一致 {same} · 不同 {diff} · 出错 {err}")
sys.exit(0 if diff == 0 and err == 0 else 1)
