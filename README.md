# 预约台集成测试

纯服务需求通过 API 验收。含 Web 页面的需求通过 Chrome DevTools MCP 打开候测地址，验证真实用户操作。各轮记录实际使用的前后端和测试提交。

三切片的成功和业务错误均须返回 HTTP 200。成功码为 `000000`，创建和同键同负载重放应返回同一条记录。业务错误须匹配具体业务码，data 可省略或为 null。

### DIWU-81 重写验收

在同一组已交付 API/Web SHA 上，给本卡的独立 MySQL 库执行候测迁移。依次运行预约、维护旧入口脚本；候补旧入口用独立日期（例如 --day 2030-01-05），并按同日期运行候补 dbcheck。预约 dbcheck 读取预约脚本日志。脚本保留历史记录，请勿把其他样例放到相同核查时段。

`python3 -B waitlist/management.py --url http://127.0.0.1:PORT` 使用 2030-02-01 起的三天，核对三种资源的 POST list/create、预约与维护 POST cancel（数字 id 字段），两种释放操作、可晋升顺序、相邻/重叠、跨新旧入口并发同键、查询和重放。用 `waitlist/dbcheck.go -day 2030-02-01` 检查前两天的真实库终态。用 integration/rollback.go 核对两种释放失败后的回滚，integration/service/check.py 核对 service 显式接收的操作人。

Chrome DevTools 使用该组合及独立日期，从预约页以 alice 创建，bob 尝试重叠并创建相邻预约。管理员在维护页创建窗口，普通用户返回预约页复现拦截，再从候补页入队。撤窗口后刷新候补和预约两页核对归属与预约 ID。保存页面操作、URL、请求、业务码、Console 和可见行。工程检查记录 Go 平台 verify 和构建包版本、Web Vue 3 适配项和 ZIP 内容。
