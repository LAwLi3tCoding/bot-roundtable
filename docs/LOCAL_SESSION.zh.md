# 受限本机浏览器会话

未认证打开 HTTP 首页不会签发会话。loopback socket peer 与匹配的 Host/Origin 无法区分浏览器和任意透明本机代理。因此安全默认保留凭据支持的 `local_runtime.py ui` 启动和手工令牌登录，不对已有安装开启新设置。

一次性码交换可带 `cookie: true`，返回 HttpOnly、SameSite=Strict、Path=/、一小时有效期的 cookie，JSON 不返回会话令牌。服务端仅保存摘要。POST `/api/ui-login/renew` 可续期有效会话；`/api/ui-login/revoke` 撤销会话并清除 cookie。过期会话不能续期，服务重启清空全部会话。cookie 修改请求必须带精确本机 Origin 和实际监听端口，带转发头请求被拒绝。受限会话不能管理成员或凭据。

HTTP cookie 不按端口隔离，同主机名其他服务仍属本机信任边界。HttpOnly 无法防御恶意本机软件或同源脚本执行。入口使用 HTTP loopback，所以 cookie 不带 Secure。不要通过 tunnel 暴露浏览器入口；头校验不能证明任意代理不存在。受支持 MCP 路由必须隔离，不能签发浏览器会话。合成测试不等于原生 OS 或厂商集成验证。

尚需产品决策：引入 OS 认证的浏览器引导，或明确接受无人值守首页登录的较弱信任模型。本实现不会默默选择其中之一。

## 在 macOS 点击“打开圆桌”

安装维护者可在安装目录一次性生成可点击应用：

```sh
.venv/bin/python scripts/local_runtime.py create-ui-launcher --output '<EXISTING_OUTPUT_DIRECTORY>/打开圆桌.app' --state-dir '<STATE_DIRECTORY>' --name default
```

将占位符替换为安装路径，含空格的路径保留引号，并使用实际实例名。生成器只创建新应用，拒绝覆盖已有文件；不读取凭据、不启动服务、不安装到 Applications、不改变认证设置。用户自行将应用放到方便的位置或加入 Dock。日常只需双击：现有 `ui` 流程自动验证并打开网页，无需知道或输入一次性码。托管服务须已运行；若没有打开页面，请维护者检查该实例。代码目录或 Python 路径移动后需重新生成入口。

快捷文件只保存路径和参数，不保存令牌或登录码；运行输出被丢弃，不写日志。测试实际执行合成 shell 入口，覆盖空格和 shell 特殊字符路径；尚未原生验证 Finder/LaunchServices 或 macOS 应用安全提示。Linux 可自行建立禁用终端显示的桌面入口，执行等价的 `local_runtime.py ui --state-dir ... --name ...`；当前生成器仅输出 macOS 应用。Windows 托管 UI 流程仍不支持。

会话从交换或成功续期起有效一小时，打开的页面每五分钟尝试续期。会话过期或服务重启后，再点击应用即可；并非每次访问输入码，也不是永久免登录。

直接网址研究：已有认证 cookie 可恢复访问；新的匿名 HTTP 请求仅凭 socket/Host/Origin 无法证明本机用户在场。后续可研究签名 OS 启动器或浏览器扩展/native messaging，通过 OS 认证通道取得短时能力再打开网页。这需要可信安装组件及明确安装授权，不能靠放宽 HTTP 检查实现；任意透明转发浏览器入口不在保证范围内。
