# 拆分计划:抽出 `book-recommendation-accounts` 服务

> 本文件是给**新 thread 独立执行**用的自包含计划。执行者无需依赖生成本文件的对话,只需读本文件 +
> 两个仓库的代码即可。所有决策已在设计讨论中拍板,见"背景与已定决策"。

---

## 背景与已定决策

当前是三服务架构中的一次拆分:

| 服务 | 职责 | 认证角色 |
|------|------|---------|
| `book-recommendation-agent`(已存在) | 推荐领域(LangGraph) | 只信任 BFF 注入的 run context,不碰认证 |
| `book-recommendation-service`(BFF,当前仓库) | chat 代理、SSE 流式、HITL | **验证方 / 网关**:只验 token + 派生身份注入 agent |
| `book-recommendation-accounts`(**本次新建**) | signup/login/发 token + family/member/child/reading-profile/policy 的 CRUD | **IdP / 签发方**:拥有 `email`/`password_hash`,签发 token |

**核心原则:签发与验证分离。** accounts 签发 token,BFF 只验证。验证方不持有凭证也能验签。

**已定决策:**
1. 新服务名 `book-recommendation-accounts`,Python 包名 `accounts`(`src/accounts`),与命名族对齐。
2. accounts 拥有:auth 签发(signup/login/hash/verify/发 token)+ family/member/child/profile/policy CRUD +
   `family_member.email`/`password_hash` 两列的所有权。
3. BFF 只保留:chat 代理 / SSE / HITL + **token 验证**(`decode_token` + `get_identity` resolver seam)。
   BFF **不再签发 token**,不再有 signup/login,不再做 family CRUD,**不再直接访问业务库**。
4. IdP 机制:**自建 RS256**——accounts 持**私钥**签,BFF 持**公钥**验;设计成以后可平滑换 Cognito
   (验证方只需把"公钥来源"换成 Cognito JWKS,代码几乎不动)。
   > ⚠️ 执行前确认:若想**一步到位上 Cognito**,则 accounts 只做"调 Cognito 管理用户",两个服务都用
   > Cognito JWKS 验签。默认按 RS256 自建执行。
5. DB 所有权:accounts 用 **Alembic** 拥有 `book_agent` schema 里账户/档案表的演进(取代双边 `create_all`)。
   这顺带修掉当前 BFF 的一个 500(见下)。
6. **写入模型 = 模型 2(单一 writer,已定,拒绝双写)**:accounts 是 family/member/child/profile/policy 这几张表的
   **唯一写入方**。**agent 不再直连这些表**,改为调用 accounts 的**内部 API**(服务级鉴权,非用户 token)。
   → **agent 仓库进入改造范围**(见"Agent 下游写入模型"一节)。

**要修的既有 bug(并入本次迁移):** 当前 BFF 的 `FamilyMember` 模型声明了 `email`/`password_hash`,但共享库
`book_agent.family_member` 表里没有这两列 → 查 `/family` 时连带加载 member 报
`UndefinedColumn: column family_member.email does not exist` → 500。本次由 accounts 的首个 Alembic 迁移补上这两列。

**双写问题(已决:消除)：** `child_profile`/`family` 过去 agent 也直接写(聊天中 HITL `create_child` 等)。
本次采用**模型 2**:accounts 唯一写入,agent 改调 accounts 内部 API。**不接受双写。** 详见"Agent 下游写入模型"一节。

---

## 当前 BFF 代码位置(执行者据此搬迁,免去重新探索)

- `src/service/routers/auth.py` — `signup` / `login` / `me`(**搬去 accounts**)
- `src/service/routers/family.py` — family/member/child/reading-profile/policy CRUD(**搬去 accounts**)
- `src/service/routers/chat.py` — 代理/SSE/HITL(**留 BFF**)
- `src/service/auth.py` — `Identity` + `get_identity`(验证 seam,dev stub + bearer);**BFF 保留验证部分,accounts 也各留一份自用**
- `src/service/security.py` — `hash_password`/`verify_password`/`create_access_token`(签发,**搬去 accounts**)+ `decode_token`(验证,**BFF 保留**)
- `src/service/schemas.py` — auth + family/member/child/... 的 Pydantic 模型 + `dump()`(CRUD 相关**搬去 accounts**;`TurnRequest`/`ResumeRequest`/`NewThreadResponse` **留 BFF**)
- `src/service/config.py` — Settings(拆:签发相关去 accounts,验证相关留 BFF)
- `src/service/db/base.py` — engine/session/Base/init_db(**搬去 accounts**;BFF 去掉直连业务库)
- `src/service/db/models/` — `family.py`/`child.py`/`_columns.py`/`__init__.py`(**搬去 accounts**)
- `src/service/db/repositories/` — `family.py`/`child.py`/`__init__.py`(**搬去 accounts**)
- `src/service/agent_client.py` — LangGraph SDK 客户端(**留 BFF**)
- `src/service/middleware.py` / `logging.py` / `main.py` — 基础设施(BFF 保留;accounts 复制一份同款)
- `tests/unit_tests/` — `test_auth`/`test_family_crud`/`test_repositories`/`test_security`(**搬去 accounts**);`test_chat_proxy`/`test_ops`(**留 BFF**)
- `Makefile` / `pyproject.toml` / `.pre-commit-config.yaml` / `CLAUDE.md` / `.env.example` — 工具基线(accounts 复制并改名)

---

## Agent 下游写入模型(已定:模型 2 — accounts 单一 writer)

**原则:用户认证只在边缘发生一次,不往下游传;agent 从不携带"用户登录 token"。** accounts 对外/对内开两个面:

| 面 | 谁调 | 鉴权 | 身份来源 |
|----|------|------|---------|
| **外部面** `/family/*` 等 | 前端 | **用户 token(RS256)** | 从 token 派生 `family_id` |
| **内部面** `/internal/*` | agent(服务) | **服务级**:`X-Service-Token`(或 mTLS)+ **网络隔离/绑内网口,不暴露公网** | `family_id`/`child_id` 作为**参数**传入 |

关键约束:
- 内部面**收 `family_id`/`child_id` 参数**,这些值由可信链路传下来(用户登录→accounts 发 token→前端带 token→BFF 验签派生
  `family_id`→注入 agent context→agent 调内部面时当参数回传)。源头仍是边缘那次验证。
- 内部面**仍做纵深归属校验**:`get_in_family(child_id, family_id)` 确认孩子属于该家庭,**不因是内部调用而跳过**(CLAUDE.md 规则)。
- ⚠️ **红线**:内部面绝不能"无鉴权 + 收 family_id 参数 + 可写"三者同时对公网开放,否则是彻底的跨家庭越权。"对内不鉴权"
  的正确含义是"不做**用户**鉴权",而非裸奔——必须有服务凭证或硬网络边界兜底。

**对 agent 仓库的影响(必须同步改):** agent 里所有**直接写** `child_profile`/`family`/reading-profile 的地方
(如 `create_child`、从对话更新 reading profile)→ 改为调用 accounts 内部 API,带 `X-Service-Token` + 传 `family_id`/`child_id`。
agent 对这些表的**直接 DB 写权限应移除**(可保留只读,或也改为走 API,按 agent 现状定)。

---

## 执行阶段

### Phase 0 — accounts 服务脚手架
- 位置:sibling 目录 `/Users/gavinxu/personal/book-recommendation-accounts`(**执行前确认路径**),`git init`。
- 复制 BFF 的工具基线并改名:`pyproject.toml`(name=`book-recommendation-accounts`,package `accounts`,package-dir `src/accounts`)、
  `Makefile`、`.pre-commit-config.yaml`、ruff/mypy/coverage 配置、`.gitignore`、`.env.example`。
- 复制 `CLAUDE.md` 并保留全部规则:PII 日志(只记异常 type)、身份服务端派生、**每个读都按 `family_id` 过滤**、
  跨家庭隔离测试、`make check`/`make ci` 为唯一验证入口。
- 复制基础设施:`middleware.py`(CorrelationId)、`logging.py`、`main.py` 骨架(健康/就绪探针 + 错误信封 + 路由挂载)。

### Phase 1 — DB 层 + 模型 + 仓库 迁到 accounts
- 把 `db/base.py`、`db/models/*`、`db/repositories/*` 整体搬到 `src/accounts/db/`。
- 保留 sqlite shim(测试用)、`session_scope`、`book_agent` schema pin、`BOOK_AGENT_DATABASE_URL`。
- BFF 删除 `src/service/db/` 整个目录及所有引用。

### Phase 2 — auth 签发迁到 accounts
- 搬 `routers/auth.py` 的 `signup`/`login`(+ `me`)到 `src/accounts/routers/auth.py`。
- 搬 `security.py` 的 `hash_password`/`verify_password`/`create_access_token` 到 accounts;
  `create_access_token` 改为 **RS256 用私钥签**,claims 保持 `sub`/`family_id`/`family_member_id`/`iat`/`exp`,新增 `iss`/`aud`。
- accounts 也需要一份 `get_identity`(验证自己签的 token,用公钥)来保护自己的 CRUD 端点 + dev stub。

### Phase 3 — family CRUD 迁到 accounts
- 搬 `routers/family.py` 到 `src/accounts/routers/family.py`(逻辑不变:`get_in_family`/`list_by_family` 全部按 `family_id` scope)。
- 搬 `schemas.py` 里 family/member/child/reading-profile/policy 模型 + `dump()` 到 accounts。
- accounts `main.py` 挂 auth + family 路由,依赖 accounts 自己的 `get_identity`。

### Phase 3.5 — accounts 内部面(给 agent 用)
- 新增 `src/accounts/routers/internal.py`,前缀 `/internal`,依赖 `service_guard`(校验 `X-Service-Token`,值来自 env `ACCOUNTS_SERVICE_TOKEN`;或 mTLS)。
- 暴露 agent 需要的写操作:如 `POST /internal/children`、`PUT /internal/children/{child_id}/reading-profile` 等,**复用外部面同一套 repository + `get_in_family` 归属校验**,只是身份从参数(`family_id`)取而非 token。
- 部署上把内部面绑内网口 / 不进公网路由(文档写清)。

### Phase 3.6 — agent 仓库改造(停止直写,改调内部 API)
- **agent 仓库路径:`/Users/gavinxu/personal/book-recommendation-agent`**(与本 BFF、新 accounts 同级 sibling)。
- 在 agent 仓库定位所有直接写 `child_profile`/`family`/reading-profile 的点(如 `create_child`)。
- 改为 HTTP 调用 accounts `/internal/*`,带 `X-Service-Token`,从 run context 取 `family_id`/`child_id` 传参。
- 移除 agent 对这些表的直接写(只读按需保留)。
- agent 的 `.env` 增加 `ACCOUNTS_INTERNAL_URL` + `ACCOUNTS_SERVICE_TOKEN`。

### Phase 4 — BFF 改成"只验证"
- `auth.py`:保留 `Identity` + `get_identity` + dev stub;`_identity_from_bearer` 改为 **RS256 用公钥验签** + 校验 `iss`/`aud`/`exp`。
- `security.py`:只保留 `decode_token`(验证);删掉 `create_access_token`/`hash_password`/`verify_password`。
- `config.py`:删 `jwt_secret`(对称);加 `jwt_public_key`(或 `jwt_jwks_url`)、`jwt_issuer`、`jwt_audience`;保留 dev stub 配置。
- 删除 BFF 的 `routers/auth.py`(signup/login)与 `routers/family.py`;`schemas.py` 只留 chat 相关。
- `main.py`:`/readyz` 去掉 DB 检查(BFF 不再连库),改为检查 agent(可选:检查 accounts)可达。
- BFF 保留:`routers/chat.py`、`agent_client.py`、middleware、logging。

### Phase 5 — 密钥管理(RS256)
- 生成 RSA keypair:`openssl genpkey -algorithm RSA -pkcs8 -out private.pem -pkeyopt rsa_keygen_bits:2048` +
  `openssl rsa -in private.pem -pubout -out public.pem`。
- accounts 持私钥(env,如 `ACCOUNTS_JWT_PRIVATE_KEY` 或文件路径);BFF 持公钥(`JWT_PUBLIC_KEY`)。
- keys 放各自 gitignored 的 `keys/` 目录;`.env.example` 里写清怎么生成。
- 定义并文档化 claims 契约:`sub`/`family_id`/`family_member_id`/`iss`/`aud`/`iat`/`exp`。

### Phase 6 — Alembic 迁移(accounts 拥有 schema)
- accounts 引入 alembic,target metadata = accounts 的 `Base.metadata`。
- 因共享库里表已存在:先对现状 `alembic stamp` 建基线,再写一个迁移 **给 `family_member` 加 `email text unique` + `password_hash text`**(即修 500 的那两列)。
- `make init-db` 由 `create_all` 改为 `alembic upgrade head`。

### Phase 7 — 本地一起跑
- 端口:agent `:2024`、BFF `:8000`、accounts `:8001`。
- accounts `.env`:`BOOK_AGENT_DATABASE_URL`(共享 `book_agent`)+ 私钥 + dev stub。
- BFF `.env`:`AGENT_URL=:2024` + 公钥 + `iss`/`aud` + dev stub(去掉 DB URL 或仅 readyz 不用)。
- 各配 uvicorn 启动(参考 BFF Makefile `run`:`uv run uvicorn accounts.main:app --reload --port 8001`)。
- 两边都保留 dev stub,便于各自离线快测。

### Phase 8 — 测试
- 搬到 accounts:`test_auth`、`test_family_crud`、`test_repositories`、`test_security`(**含跨家庭隔离测试**)。
- BFF:`test_chat_proxy`、`test_ops` 保留;重写 `test_auth` 为**验证路径**——用测试 RSA keypair 签一个 token 喂给 BFF,断言验签通过/坏 token 401/dev stub。
- 两个仓库都要 `make check` 全绿(lint + mypy + codespell + test);push 前 `make ci`(coverage `fail_under`)。

---

## 执行前需你确认的点
1. **新仓库位置**:默认 `/Users/gavinxu/personal/book-recommendation-accounts`,`git init`(是否要 remote?)。
2. **IdP 机制**:默认 **RS256 自建**;若要现在就上 Cognito,请说明。
3. **BFF 是否彻底不连业务库**:默认是(`/readyz` 改查 agent 可达)。
4. **用户管理"对外入口" = A(已定)**:前端**直连 accounts**,不经 BFF 转发。accounts 同时提供**外部面**(用户 token)
   和**内部面**(服务凭证)两套接口。API Gateway 后续再加(那时业务代码不用改,只加路由)。
5. **内部面服务鉴权 = Service Token(已定)**:agent 调用带 `X-Service-Token` 请求头,accounts 比对
   env `ACCOUNTS_SERVICE_TOKEN`,配合内部面绑内网 / 不暴露公网。将来需要时再升级 mTLS(只换 `service_guard` 实现)。

> 注:**写入模型已定为模型 2(accounts 单一 writer,无双写),agent 仓库在改造范围内**,不再是待定项。

## 验收标准
- accounts:`/auth/signup` → 拿 RS256 token;`/family` 等 CRUD 正常;跨家庭隔离测试通过;`make check` 绿。
- BFF:用 accounts 发的 token 走 chat 代理链路,验签通过、身份正确注入 agent;不含任何签发/CRUD/业务库代码;`make check` 绿。
- 之前 `/family` 的 500 消失(由 Alembic 迁移补列解决)。
