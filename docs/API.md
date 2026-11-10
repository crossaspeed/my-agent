# API 说明

- 在线文档：`http://127.0.0.1:8000/docs`（Swagger UI）、`/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- 基础路径：`/api/v1`（下文省略前缀）
- 鉴权：`Authorization: Bearer <JWT>`（登录/注册接口除外）

## 1. 统一响应信封

所有业务接口（含错误）都返回同一信封，便于前端统一解包：

```json
{ "code": 0, "message": "ok", "data": { } }
```

- `code = 0` 表示成功；非 0 为业务错误码
- `data` 为业务负载；`message` 为可展示给用户的中文提示
- 每个响应头带 `X-Trace-Id`，与后端日志中的 `trace_id` 一致，便于排查

错误示例（HTTP 422）：

```json
{
  "code": 1011,
  "message": "知识库未覆盖该知识点，请补充课件或调整知识点",
  "data": null
}
```

## 2. 错误码

| code | HTTP | 含义 |
|---|---|---|
| 0 | 200 | 成功 |
| 1001 | 400 | 请求参数不合法 |
| 1002 | 401 | 未登录或登录已过期（前端应跳登录页） |
| 1003 | 403 | 无权访问该资源（角色/课程成员校验失败） |
| 1004 | 404 | 资源不存在 |
| 1005 | 409 | 资源冲突（重复用户名、重复提交等） |
| 1010 | 422 | 文档解析失败 |
| 1011 | 422 | 知识库未覆盖（检索无据，拒绝编题/编答案） |
| 1029 | 429 | 请求过于频繁（出题/导学限流） |
| 4220 | 422 | Pydantic 参数校验失败（`data` 内含字段级原因） |
| 5001 | 504 | 模型响应超时 |
| 5002 | 503 | 模型不可用（已熔断） |
| 5003 | 500 | 智能体执行失败（`data.node` 指出失败节点） |
| 5000 | 500 | 未预期异常（不返回堆栈） |

## 3. 接口清单

### 3.1 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/register` | 注册（默认学生；`role=teacher` 需 `invite_code`；首个用户自动 admin） |
| POST | `/auth/login` | 登录，返回 `access_token` + `user` |
| GET | `/auth/me` | 当前登录用户 |
| POST | `/auth/change-password` | 修改密码（校验旧密码） |

### 3.2 课程 / 成员 / 知识点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/courses` | 我的课程（教师=拥有，学生=已加入），含统计与 `my_role` |
| POST | `/courses` | 创建课程（**仅教师/管理员**） |
| GET | `/courses/{id}` | 课程详情（含 `stats`） |
| PATCH | `/courses/{id}` | 修改课程（创建者） |
| GET | `/courses/{id}/members` | 成员列表 |
| POST | `/courses/{id}/members` | 批量添加学生（`{"usernames":[...]}`） |
| GET | `/courses/{id}/knowledge-points` | 知识点树（递归 `children`，含 `chunk_count`） |
| POST | `/courses/{id}/knowledge-points` | 新建知识点 |
| POST | `/courses/{id}/knowledge-points:auto` | 从课件标题结构自动抽取知识点树 |
| PATCH | `/knowledge-points/{kp_id}` | 修改知识点 |
| DELETE | `/knowledge-points/{kp_id}` | 删除知识点 |

### 3.3 知识库（文档 / 分块 / 检索）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/courses/{id}/documents` | 上传课件（multipart，字段名 `file`），返回 `document_id` + `job_id` |
| GET | `/courses/{id}/documents` | 文档列表（含 `status`、`chunk_count`、`error_msg`） |
| GET | `/documents/{id}` | 文档详情 |
| GET | `/documents/{id}/chunks` | 分块列表；支持 `q` 关键词、`around` 取上下文、分页 |
| POST | `/documents/{id}/reparse` | 重新解析（重排队） |
| DELETE | `/documents/{id}` | 删除文档（级联清理分块与向量） |
| POST | `/courses/{id}/search` | 混合检索调试接口（论文实验用），返回命名空间 `{query,count,items}` |

上传约束：`.pdf/.pptx/.docx/.md/.txt`，大小 ≤ `MAX_UPLOAD_MB`（默认 50），扩展名白名单 + magic 嗅探 + sha256 去重。

### 3.4 题目与审核

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/courses/{id}/questions:generate` | 异步出题，返回 `{job_id, estimated_seconds}` |
| GET | `/courses/{id}/questions` | 题库列表（`page/size/status/type/kp_id/keyword`） |
| GET | `/courses/{id}/questions/review-queue` | 待审核题目 |
| GET | `/questions/{id}` | 题目详情（学生仅在已交卷后可见答案） |
| PATCH | `/questions/{id}` | 编辑题目（题干/选项/答案/要点/难度/知识点） |
| DELETE | `/questions/{id}` | 归档（软删） |
| POST | `/questions/{id}:review` | 审核单题 `{"action":"approve|reject","note":"..."}` |
| POST | `/questions:batch-review` | 批量审核 `{"ids":[...],"action":"approve"}` |

出题请求体：

```json
{
  "course_id": 1,
  "kp_ids": [3, 4],
  "types": { "single": 5, "multiple": 2, "judge": 2, "short": 1 },
  "difficulty": { "easy": 0.2, "medium": 0.6, "hard": 0.2 },
  "requirements": "侧重三次握手与拥塞控制的对比",
  "auto_publish": false
}
```

题型枚举：`single | multiple | judge | short | essay`。

### 3.5 试卷与作答

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/papers` | 组卷（`mode=manual` 传 `question_ids`；`mode=auto` 传 `config{kp_ids,types,difficulty}`） |
| GET | `/papers?course_id=` | 试卷列表（含我的作答状态与分数） |
| GET | `/papers/{id}` | 试卷详情（含答案，教师用） |
| GET | `/papers/{id}/for-student` | 学生端试卷（**服务层剥离答案**） |
| POST | `/papers/{id}:publish` | 发布（校验题目均为 published） |
| GET | `/papers/{id}/stats` | 班级成绩（提交数/均分/极值/明细） |
| POST | `/papers/{id}/attempts` | 开始作答（幂等，重复调用返回既有 attempt） |
| GET | `/attempts/{id}` | 作答详情（草稿恢复） |
| PUT | `/attempts/{id}/answers/{question_id}` | 保存单题草稿 `{"value":..., "flagged":false}` |
| POST | `/attempts/{id}:submit` | 交卷并触发异步阅卷（幂等） |
| GET | `/attempts/{id}/grading-status` | 阅卷进度（前端 1.5s 轮询） |
| GET | `/attempts/{id}/report` | 成绩报告（总分/逐题/掌握度/错因/`course_id`） |
| GET | `/attempts/{id}/stats/kp-mastery` | 知识点掌握度（雷达数据） |
| GET | `/me/attempts` | 我的测评记录 |

作答值约定：`single=str`，`multiple=list[str]`，`judge=bool`，`short/essay=str`。

### 3.6 学情统计（教师）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/courses/{id}/stats/overview` | 课程概览（课件/分块/题库/已发布/测评数/均分/最近任务） |
| GET | `/courses/{id}/stats/error-heatmap` | 班级错题分布（知识点 × 错因标签） |
| GET | `/courses/{id}/jobs` | 课程任务列表（`limit`、`job_type`） |

### 3.7 导学（SSE）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/tutor/sessions` | 我的会话列表 |
| POST | `/tutor/sessions` | 创建会话并返回开场讲解：`{course_id, question_id}` 或 `{answer_id}` |
| GET | `/tutor/sessions/{id}` | 会话详情 + 历史消息 + 推荐练习 |
| POST | `/tutor/sessions/{id}/messages` | 发送消息，**SSE 流式返回** |
| DELETE | `/tutor/sessions/{id}` | 删除会话 |

### 3.8 任务与运维

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/jobs/{task_id}` | 任务状态（`status/progress/stage/result/error_msg`） |
| POST | `/jobs/{task_id}:retry` | 重试失败任务 |
| GET | `/admin/health` | 依赖健康检查（DB / 向量库 / LLM / 队列） |
| POST | `/admin/reindex` | 重建向量索引（换 embedding 模型后必须执行） |
| GET | `/admin/llm-calls` | LLM 调用统计（总量/成功率/平均时延/token/按场景/按天） |
| GET | `/health` | 存活探针（不需鉴权） |

## 4. SSE 协议

请求：`POST /api/v1/tutor/sessions/{id}/messages`，`Content-Type: application/json`，**需带 Authorization 头**（因此前端用 `fetch` + 流式读取，而非 `EventSource`）。

```
event: meta
data: {"session_id":12,"message_id":88}

event: token
data: {"delta":"三次握手"}

event: refs
data: {"refs":[{...}],"practice":[{...}],"diagnosis":"..."}

event: done
data: {"message_id":89,"content":"完整回复","refs":[...],"tokens":0}

event: error
data: {"code":5001,"message":"模型输出中断：...","partial":"已生成的前缀"}
```

| 事件 | 时机 | 前端处理 |
|---|---|---|
| `meta` | 已落库用户消息 | 确认发送成功，开始渲染 |
| `token` | 逐 token | 追加到当前气泡 |
| `refs` | 讲解结束前 | 展示「查看引用溯源」按钮、推荐练习 |
| `done` | 全部完成并落库 | 结束流式态，刷新会话历史 |
| `error` | 异常 | 展示 `message`，保留 `partial` 内容，允许重试 |

部署注意：Nginx 必须 `proxy_buffering off;`，后端已带 `X-Accel-Buffering: no`。

## 5. 调用示例

```bash
# 登录
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher","password":"123456"}'

TOKEN=<access_token>

# 上传课件
curl -s -X POST http://127.0.0.1:8000/api/v1/courses/1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@第3章-传输层.pdf"

# 出题（拿 job_id 后轮询）
curl -s -X POST http://127.0.0.1:8000/api/v1/courses/1/questions:generate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"course_id":1,"types":{"single":3},"kp_ids":[3]}'

curl -s http://127.0.0.1:8000/api/v1/jobs/<job_id> -H "Authorization: Bearer $TOKEN"

# 检索调试
curl -s -X POST http://127.0.0.1:8000/api/v1/courses/1/search \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"三次握手为什么不能是两次","top_k":5}'

# 导学 SSE
curl -N -X POST http://127.0.0.1:8000/api/v1/tutor/sessions/1/messages \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"那为什么不用两次握手？"}'
```
