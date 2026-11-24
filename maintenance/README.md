### DIWU-68 维护窗口回归

从 QA 仓根运行 `python3 -B maintenance/regression.py`。仅使用 Python 3 标准库，默认在系统分配的回环端口启动内存 HTTP 契约桩。输出逐请求输入、身份、响应和最终列表。键标签在实际请求前统一加本轮随机前缀。任一断言失败以非零状态退出。

联调命令为 `python3 -B maintenance/regression.py --base-url http://127.0.0.1:PORT`，将 PORT 替换为本卡 API 端口。使用已迁移、专用且无预约、维护或候补记录的测试库。每次运行创建真实数据并撤销成功创建的活动记录，保留历史和幂等记录，断言失败时保留现场。不要并行使用同一库。

| 步骤 | 输入和预期 |
|---|---|
| 身份和参数 | 缺身份、未知身份、普通用户写维护均返回 FORBIDDEN。缺查询边界、缺幂等键或零时长均返回 INVALID_INPUT。普通用户可读，不能撤销维护。 |
| 阻挡与重放 | 2030-01-02 UTC，admin 建 env-a 10–11，重放同 ID，换环境重用 key 为 KEY_REUSED。维护或预约重叠均 MAINTENANCE_CONFLICT。 |
| 查询和边界 | 10:30–11 查到原记录，11–12 和 env-b 查不到；两处可建预约。撤销两次返回同一 cancelled 记录，列表移除。 |
| 预约优先占用 | alice 已预约时建维护报 BOOKING_CONFLICT，预约保留，维护列表为空。 |
| 同时提交 | 两个 HTTP 客户端在栅栏处同步，向同一环境同一时段提交预约和维护。两笔均为 HTTP 200，恰有一笔业务码为 000000，另一笔的冲突码与赢家对应。分别 GET 核对仅赢家可见，撤销后复查两环境。 |

契约桩以进程内互斥模拟竞争结果。数据库并发、锁后读取、绑定参数、事务失败回滚及存储终态须针对授权 MySQL 单独取证。

### 浏览器验收步骤

在本轮 Web 候测包的维护页打开 Chrome DevTools MCP，选择 env-a。管理员查询后创建固定窗口，保存成功提示和新增行，刷新确认行仍可见。尝试建立重叠窗口，核对 HTTP 200、MAINTENANCE_CONFLICT 与可见提示。切普通身份核对查询、创建与撤销权限；以 admin 撤销，确认记录消失。对每步记录 URL、请求方法、路径、身份、状态码、响应及 Console 错误。页面连接桩时注明桩来源。

### Go 路由守卫

运行 `python3 maintenance/route_guards.py /path/to/api`，参数为已合入公共 Gin 路由和维护模块的候测 API 检出。Go overlay 将测试挂到 controller 包，在 Gin 注册生产维护模块，逐个调用 ServeHTTP 并检查 8 个应在访问仓储前返回的请求。输出身份、输入、HTTP 状态与业务响应。本组可在没有 MySQL 时独立执行。

如需在浏览器复验契约桩，单独运行 `python3 -B maintenance/fixture.py --port 19668`。在包含维护路由的 Web 检出中运行 `DEV_API_TARGET=http://127.0.0.1:19668 npm run dev -- --host 127.0.0.1 --port 19669 --strictPort`，打开 `http://127.0.0.1:19669/aisol-env-booking-web/maintenance`。若端口已用，给本卡另选一对空闲端口。
