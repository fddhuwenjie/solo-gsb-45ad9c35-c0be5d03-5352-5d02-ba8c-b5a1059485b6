# 循环赛积分榜 API

基于 FastAPI 的循环赛（round-robin）积分榜服务。提交参赛队伍与已完赛比分，返回排名及各项统计数据；也可提交未赛对阵的候选比分，枚举所有赛果组合，分析各队跻身前 K 名的出线形势。

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
tests/
  test_standings.py
  test_scenarios.py
Dockerfile
docker-compose.yml
requirements.txt
```
