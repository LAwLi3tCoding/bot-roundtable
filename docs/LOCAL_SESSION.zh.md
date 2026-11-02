# 受限本机浏览器会话

未认证打开 HTTP 首页不会签发会话。loopback socket peer 与匹配的 Host/Origin 无法区分浏览器和任意透明本机代理。因此安全默认保留凭据支持的 `local_runtime.py ui` 启动和手工令牌登录，不对已有安装开启新设置。

一次性码交换可带 `cookie: true`，返回 HttpOnly、SameSite=Strict、Path=/、一小时有效期的 cookie，JSON 不返回会话令牌。服务端仅保存摘要。POST `/api/ui-login/renew` 可续期有效会话；`/api/ui-login/revoke` 撤销会话并清除 cookie。过期会话不能续期，服务重启清空全部会话。cookie 修改请求必须带精确本机 Origin 和实际监听端口，带转发头请求被拒绝。受限会话不能管理成员或凭据。

HTTP cookie 不按端口隔离，同主机名其他服务仍属本机信任边界。HttpOnly 无法防御恶意本机软件或同源脚本执行。入口使用 HTTP loopback，所以 cookie 不带 Secure。不要通过 tunnel 暴露浏览器入口；头校验不能证明任意代理不存在。受支持 MCP 路由必须隔离，不能签发浏览器会话。合成测试不等于原生 OS 或厂商集成验证。

尚需产品决策：引入 OS 认证的浏览器引导，或明确接受无人值守首页登录的较弱信任模型。本实现不会默默选择其中之一。
