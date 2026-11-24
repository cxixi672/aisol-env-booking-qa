# DIWU-70 预约与取消回归

从 QA 仓库根目录执行，使用 Python 3 标准库。脚本逐请求输出身份、输入、HTTP 状态、原始响应，断言失败退出非零。

- 独立契约桩：`python3 -B bookings/check.py`。自动分配 loopback 端口，退出即清空。桩只实现本切片，使用进程锁模拟串行写入。
- 候测 API：`python3 -B bookings/check.py --base-url http://127.0.0.1:端口`。使用本卡专用已迁移测试库，env-a、env-b 对应时段须空闲且没有候补与维护。每轮用新键前缀，结束时取消本轮预约。取消历史和已用键会保留；数据库终态与事务回滚另行核对。
- 浏览器配桩：`python3 -B bookings/stub.py --port 18770`。Web 将 /api 代理到该地址；请为本卡单独启动实例。

固定日期 2030-01-02 UTC。alice 与 bob 同时预约 env-a 10–11，核对唯一赢家、失败包、同键相同负载重放和异负载拒绝。carol 同键并发预订相邻 11–12；另一用户用同名键预订 env-b 10–11。查询单段和两段核对半开边界、创建顺序、环境隔离。越权取消后原记录仍 active；本人重复取消返回相同 cancelled 记录并可重新预订。覆盖缺失或未知身份、缺键、空时段与缺查询参数。

页面验收使用 Chrome DevTools MCP 打开 /aisol-env-booking-web/，选择 alice 和 env-a，在预约页创建固定时段。切换 bob 尝试重叠预约，记录冲突提示与原行。核对相邻时段与 env-b，切回所有者取消并刷新。逐项保留可见结果、Network 请求及 Console。记录 Web/API/QA SHA 和 API 为真实路由或契约桩。

真实 MySQL 验收另需专库连接。通过结构化查询与绑定参数核对并发后的业务行、幂等记录、取消状态与失败事务的写入。

真库核验命令：先把对候测 API 的完整 stdout 保存为 run.log。在同组合 API 检出的 go.mod 所在目录，注入专库只读 DSN 环境变量 BOOKING_QA_MYSQL_DSN，执行 `go run /path/to/qa/bookings/dbcheck.go /path/to/run.log`。脚本只接受成功的外部目标运行日志。用 sqrl 按本轮身份、键及预约 ID 绑定查询，逐条核对缓存成功响应、失败专用键未残留、预约取消后的归属与精确时间；不会输出 DSN。
