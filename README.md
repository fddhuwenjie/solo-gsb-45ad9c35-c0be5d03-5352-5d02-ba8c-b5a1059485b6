# 循环赛积分榜 API

基于 FastAPI 的循环赛（round-robin）服务。提交参赛队伍与已完赛比分，返回排名及各项统计数据；也可提交未赛对阵的候选比分，枚举所有赛果组合，分析各队跻身前 K 名的出线形势；还可以根据不可参赛轮次与固定比赛自动生成完整的单循环赛程。

## 排名规则

1. **积分**：胜 3 分、平 1 分、负 0 分。
2. **同分队伍**：仅使用这些队伍之间的比赛建立"小联赛"，依次比较小联赛积分、净胜球、进球数。
3. **部分分出**：若小联赛只分出部分队伍，对仍同分的小组**重新建立小联赛**（递归）再比较。
4. **仍同分**：依次比较总净胜球、总进球数、队伍 ID（字典序升序）。

## 校验规则

出现以下情况时返回 `422`：

- 比赛中出现未知队伍（不在 `teams` 列表中）
- 队伍与自己比赛（`home == away`）
- 重复对阵（同一对队伍出现两次，主客互换也算重复；未赛对阵不得与已赛或其他未赛项重复）
- 队伍 ID 重复、空队伍列表、负比分
- 未赛对阵的候选比分为空或含负数
- `top_k` 小于 1
- 候选比分组合数超过 100000

赛程生成接口 `POST /round-robin-schedules` 出现以下情况时同样返回 `422`：

- 队伍数不在 2～8 之间，或队伍 ID 重复
- 总轮数低于该队数完成单循环的最少轮数（偶数队 `n-1`、奇数队 `n`）或超过 12
- 不可参赛轮次或固定比赛的轮次超出 `1..rounds` 范围
- 固定比赛含未知队伍、队伍与自己比赛，或同一对队伍出现两次固定比赛
- 同一支队伍在同一轮被安排两场固定比赛
- 固定比赛落在任一参赛队的不可参赛轮次
- 不存在满足全部约束（对阵完整、避开不可参赛轮次、主客均衡、不连续三场同主客）的赛程

## 启动方式

### Docker Compose（推荐）

```bash
docker compose up --build
```

### Dockerfile

```bash
docker build -t standings-api .
docker run -p 8000:8000 standings-api
```

### 本地开发

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 访问端口

服务监听 **8000** 端口：

- 积分榜端点：`POST http://localhost:8000/standings`
- 出线形势端点：`POST http://localhost:8000/qualification-scenarios`
- 赛程生成端点：`POST http://localhost:8000/round-robin-schedules`
- Swagger 交互文档：`http://localhost:8000/docs`
- OpenAPI 规范：`http://localhost:8000/openapi.json`

## 请求示例

### POST /standings

```bash
curl -X POST http://localhost:8000/standings \
  -H "Content-Type: application/json" \
  -d '{
    "teams": ["alpha", "bravo", "charlie"],
    "matches": [
      {"home": "alpha", "away": "bravo", "home_score": 2, "away_score": 1},
      {"home": "bravo", "away": "charlie", "home_score": 1, "away_score": 1},
      {"home": "alpha", "away": "charlie", "home_score": 0, "away_score": 0}
    ]
  }'
```

响应：

```json
{
  "standings": [
    {"rank": 1, "team": "alpha", "played": 2, "wins": 1, "draws": 1, "losses": 0,
     "goals_for": 2, "goals_against": 1, "goal_difference": 1, "points": 4},
    {"rank": 2, "team": "charlie", "played": 2, "wins": 0, "draws": 2, "losses": 0,
     "goals_for": 1, "goals_against": 1, "goal_difference": 0, "points": 2},
    {"rank": 3, "team": "bravo", "played": 2, "wins": 0, "draws": 1, "losses": 1,
     "goals_for": 2, "goals_against": 3, "goal_difference": -1, "points": 1}
  ]
}
```

### POST /qualification-scenarios

在 `teams`、`matches`（已赛）之外，额外提供：

- `top_k`：出线名额（名次 ≤ top_k 视为出线）。
- `remaining`：未赛对阵列表，每项含 `home`、`away` 和有限的候选比分 `candidates`（至少一个，均非负）。

服务枚举所有候选比分组合（笛卡尔积，超过 100000 时返回 `422`），对每种组合套用与 `/standings` 相同的排名规则，给出每队的**最佳名次** `best_rank` 与**最差名次** `worst_rank`，并据此分类：

- `guaranteed`：最差名次 ≤ top_k，铁定出线；
- `possible`：最差名次 > top_k 但最佳名次 ≤ top_k，仍有可能；
- `eliminated`：最佳名次 > top_k，确定无缘。

每个名次极值都附带一组**完整的未赛赛果**作为见证（`best_witness` / `worst_witness`，与 `remaining` 一一对应、顺序一致），将其与已赛比分一起提交 `/standings` 可复现对应名次。响应按最佳名次、最差名次、队伍 ID 排序，`combinations` 为实际枚举的组合数。

```bash
curl -X POST http://localhost:8000/qualification-scenarios \
  -H "Content-Type: application/json" \
  -d '{
    "teams": ["alpha", "bravo", "charlie", "delta"],
    "matches": [
      {"home": "alpha", "away": "bravo", "home_score": 2, "away_score": 0},
      {"home": "alpha", "away": "charlie", "home_score": 2, "away_score": 0},
      {"home": "bravo", "away": "charlie", "home_score": 1, "away_score": 0}
    ],
    "top_k": 2,
    "remaining": [
      {"home": "delta", "away": "alpha",
       "candidates": [
         {"home_score": 1, "away_score": 0},
         {"home_score": 0, "away_score": 0},
         {"home_score": 0, "away_score": 1}
       ]},
      {"home": "delta", "away": "bravo",
       "candidates": [
         {"home_score": 1, "away_score": 0},
         {"home_score": 0, "away_score": 0},
         {"home_score": 0, "away_score": 1}
       ]},
      {"home": "delta", "away": "charlie",
       "candidates": [
         {"home_score": 1, "away_score": 0},
         {"home_score": 0, "away_score": 0},
         {"home_score": 0, "away_score": 1}
       ]}
    ]
  }'
```

响应（bravo/charlie 的见证从略）：

```json
{
  "top_k": 2,
  "combinations": 27,
  "scenarios": [
    {
      "team": "alpha",
      "status": "guaranteed",
      "best_rank": 1,
      "worst_rank": 2,
      "best_witness": [
        {"home": "delta", "away": "alpha", "home_score": 1, "away_score": 0},
        {"home": "delta", "away": "bravo", "home_score": 0, "away_score": 0},
        {"home": "delta", "away": "charlie", "home_score": 0, "away_score": 0}
      ],
      "worst_witness": [
        {"home": "delta", "away": "alpha", "home_score": 1, "away_score": 0},
        {"home": "delta", "away": "bravo", "home_score": 1, "away_score": 0},
        {"home": "delta", "away": "charlie", "home_score": 1, "away_score": 0}
      ]
    },
    {"team": "delta", "status": "possible", "best_rank": 1, "worst_rank": 4,
     "best_witness": ["..."], "worst_witness": ["..."]},
    {"team": "bravo", "status": "possible", "best_rank": 2, "worst_rank": 3,
     "best_witness": ["..."], "worst_witness": ["..."]},
    {"team": "charlie", "status": "eliminated", "best_rank": 3, "worst_rank": 4,
     "best_witness": ["..."], "worst_witness": ["..."]}
  ]
}
```

### POST /round-robin-schedules

生成完整的单循环赛程。请求字段：

- `teams`：2～8 支队伍 ID（不可重复）。
- `rounds`：总轮数（1 基），必须介于完成单循环所需的最少轮数与 12 之间。最少轮数：偶数队为 `n-1`（每轮都可全部配对），奇数队为 `n`（每轮有一队轮空）。
- `unavailable_rounds`（可选）：每支队伍的不可参赛轮次，形如 `{"alpha": [1, 3]}`。
- `fixed_matches`（可选）：固定比赛列表，每项含 `round`、`home`、`away`，其轮次与主客关系必须原样保留。

赛程满足：

- 每对队伍恰好比赛一次（主客互换也算同一对）；
- 每队每轮至多一场（多出的轮次为轮空）；
- 非固定比赛避开所有相关队伍的不可参赛轮次；
- 每队主场数与客场数之差不超过 1；
- 不得连续三场同为主场或同为客场（按各队**实际参赛的比赛顺序**判断，轮空轮不打断连续计数）。

每轮的比赛按主队、再按客队 ID 升序排列；在所有可行方案中，选择逐轮序列字典序最小者（逐轮比较，轮内即上述排序后的 `(home, away)` 序列；空轮按标准列表序排在任何非空轮之前）。相同请求始终返回相同结果，且结果与 `teams` 数组的排列顺序无关。

无解（不可参赛轮次/固定比赛导致无法满足上述约束）或固定项冲突时返回 `422` 并在 `detail` 中说明原因。

```bash
curl -X POST http://localhost:8000/round-robin-schedules \
  -H "Content-Type: application/json" \
  -d '{
    "teams": ["alpha", "bravo", "charlie", "delta"],
    "rounds": 4,
    "unavailable_rounds": {"alpha": [1]},
    "fixed_matches": [{"round": 2, "home": "charlie", "away": "alpha"}]
  }'
```

响应（每轮一个条目，无比赛的轮次 `matches` 为空列表；此例中第 1 轮可以完全轮空并仍能在后续轮次完赛，故字典序最小方案将第 1 轮留空，固定比赛 `charlie(主) vs alpha(客)` 保留在第 2 轮）：

```json
{
  "teams": ["alpha", "bravo", "charlie", "delta"],
  "rounds": 4,
  "schedule": [
    {"round": 1, "matches": []},
    {"round": 2, "matches": [
      {"home": "bravo", "away": "delta"},
      {"home": "charlie", "away": "alpha"}
    ]},
    {"round": 3, "matches": [
      {"home": "alpha", "away": "bravo"},
      {"home": "charlie", "away": "delta"}
    ]},
    {"round": 4, "matches": [
      {"home": "bravo", "away": "charlie"},
      {"home": "delta", "away": "alpha"}
    ]}
  ]
}
```

无解示例（alpha 在第 1、2 轮均不可参赛，3 轮内无法完成 2 场比赛）：

```bash
curl -X POST http://localhost:8000/round-robin-schedules \
  -H "Content-Type: application/json" \
  -d '{
    "teams": ["alpha", "bravo", "charlie"],
    "rounds": 3,
    "unavailable_rounds": {"alpha": [1, 2]}
  }'
# HTTP 422
# {"detail": "no feasible schedule exists: the unavailable rounds and fixed matches
#  leave no way to complete the round robin while satisfying the home/away constraints"}
```

## 运行测试

```bash
pip install -r requirements.txt
pytest
```

## 项目结构

```
app/
  main.py        # FastAPI 应用与路由
  schemas.py     # 请求/响应模型
  standings.py   # 积分榜计算与校验逻辑
  scenarios.py   # 出线形势枚举与名次极值计算
  scheduling.py  # 单循环赛程生成（校验 + 字典序最小回溯搜索）
tests/
  test_standings.py
  test_scenarios.py
  test_schedules.py
Dockerfile
docker-compose.yml
requirements.txt
```
