# webOS Locale Unlock

在已经 Root 的 LG webOS 电视上启用隐藏的系统 UI 语言，同时保留原有地区。

**Unlock the language, not the region.**

[English](README.md) · [技术方法](docs/methodology.md) · [兼容性](docs/compatibility.md) · [恢复](docs/recovery.md) · [安全与隐私](SECURITY.md)

v0.1.0 提供 Audit、Backup、Apply、Verify、Restore、Report 六个 CLI 命令。前提是电视已经 Root 且 HBC 正常；不提供 Root 漏洞、改区、工程菜单或固件工具。

**方法有实机证据，新客户端尚未完成独立实机验收。** 原方法仅在日本版 OLED42C5PJA、43.21.96、webOS 26 上成功。本版开发只执行本地模拟测试，没有修改电视。写入严格限制于这一型号、固件、日本基线与 `zh-Hans-CN` 目标；其他设备和语言未验证。

## 为什么无需换区

固件中存在翻译资源，不等于语言菜单会列出该语言。已检查的电视包含中文资源，但 `langSelJP` 只列出日语、英语。原生 UI 偏好可使用已有资源，国家、服务国家和硬件地区保持日本。这不能推导为所有 webOS 设备都支持。

请求保留完整当前 `localeInfo`，仅修改 `locales.UI`。写入后逐字段比较；明确指定 `--allow-stt-sync` 时，只额外接受 STT 自动跟随同一目标语言。TV OSD、FMT、NLP、AUD/AUD2、键盘、国家、服务国家、语言组与 NVRAM 均不作为修改目标。

## 真实验证与限制

| 项目 | 原方法实测 |
| --- | --- |
| 设备 | OLED42C5PJA.AJLQLJD / 43.21.96 / webOS 26，内部 11.2.0 |
| 前提 | Root、HBC 0.7.3 |
| 中文显示 | Home、快捷设置、完整设置主要内容，经所有者目视确认 |
| 实际变化 | UI、STT → zh-Hans-CN；NLP 仍为日语 |
| 日本配置 | Area 31622；JP / JP / 6；JPN / JP / langSelJP，保持原值 |
| 原有功能 | 所有者确认 HDMI、画质、声音、联网及原有日本广播正常；Root/HBC 保持 |
| 已知显示问题 | 菜单语言标签显示“正在加载”；部分翻译键可能回退 |
| 保持原样 | TV OSD 日语；键盘日语、英语 |
| 未验证 | 中文跨重启、断电持久性；语音识别准确性；其他机型；新 CLI 的端到端实机操作 |

这不是完整中文化。STT 改变后不能保证日语语音行为不变。只允许用户明确接受已知的语言标签 Loading 问题；黑屏、菜单无法操作或其他异常必须回滚。

## 环境与安装

- Windows、Python 3.10+；本地源码测试使用 Python 3.14。
- 已有可用 SSAP 配对密钥及应用启动权限。本版不创建或保存新配对。
- 电视已有 Root/HBC exec、Tiny Browser、Node、setsid、luna-send；不在电视上安装工具。
- 可信的 IPv4 私有局域网，电视能访问 Windows 临时 HTTP 接收端；禁止公网转发。
- 唯一运行依赖为 Apache-2.0 的 [websocket-client](https://github.com/websocket-client/websocket-client)，处理 WebSocket；其余 Windows 代码使用标准库。

审阅源码后，在仓库中安装：

```powershell
py -m pip install .
webos-locale --help
```

该命令会安装声明的依赖和构建要求。本轮审查没有安装依赖，也没有验证 wheel 构建。未复制第三方 SSAP 或漏洞源码。

## 使用

下例 IP 是虚构地址，须替换为自己的电视地址。将已有密钥保存在仓库外的 `ssap.key`；私有目录必须限制本机访问，备份未加密。

```powershell
$state = Join-Path $env:LOCALAPPDATA 'webos-locale-private'
$tv = @('--host', '10.23.45.67', '--key-file', "$state\ssap.key", '--state-dir', $state)

webos-locale @tv audit --ui zh-Hans-CN
webos-locale @tv backup
```

Audit、Backup 不写电视偏好，但会暂时通过 SSAP 打开引导页面，调用现有 HBC exec，完成后返回 Home。只读取限定字段，不导出整个数据库或系统日志；缺少路径或权限即停止，不修改 ACL。

如果已有配对需要原来的身份 manifest，可在 `$tv` 中加入 `--manifest-file` 与私有 JSON 文件路径。仅接受受限应用启动权限及无签名的最小字段。新适配层的配对兼容性尚待实机验收；不要为了绕过失败批准意外出现的新配对提示。

确认兼容后：

```powershell
webos-locale @tv apply --ui zh-Hans-CN --allow-stt-sync
```

程序显示当前 UI、目标 UI、STT 联动、影响及备份位置，要求输入 `APPLY`。正式目标写入前，会确认电视端独立 Root 守护进程，并实际终止一个测试子进程、写回完整原值验证恢复。因此恢复演练包含一次**同值偏好写入**，不应误称为只读；它和异常恢复写入不计入那一次目标语言请求。

请求、原始回执、即时与延迟回读、完整差异先保存在 Windows，之后才判定结果。未知变化、接口拒绝、写入进程退出、控制端失联和超时均触发完整原值恢复。目视阶段默认 600 秒，可配置 30–900 秒；`--yes` 只能跳过初始确认，不能跳过目视验收。

按提示确认 Home、快捷设置、完整设置以及原有电视功能。只有确认完成才保留状态；不自动重启。重复应用当前目标是空操作。已知 Loading 标签需单独输入 `ACCEPT_LOADING` 接受，不能据此接受其他异常。

## 验证、恢复和报告

使用 Apply 输出的真实备份路径，下例文件名为占位符：

```powershell
$backup = "$state\locale-TIMESTAMP.backup.json"
webos-locale @tv verify --backup $backup --ui zh-Hans-CN --allow-stt-sync
webos-locale @tv restore --backup $backup

# 以下仅在 Windows 离线生成白名单报告：
webos-locale report --session "$state\session-SESSIONID" --output .\public-report.json
```

Restore 要求输入 `RESTORE`，先建立恢复前备份，再通过同样的独立恢复演练。恢复依据是签名校验通过的完整原始对象，**不假定原始语言是日语**。必须是同一配对密钥、同一受保护环境；修改后的新备份无法重建更早状态。保留原密钥，勿将备份或私有事件提交到公开仓库。Report 只导出白名单 JSON，分享前仍应检查。

操作前阅读[恢复说明](docs/recovery.md)。恢复依赖电视仍能运行、Root 和 Settings Service 可用，不能承诺无法启动、断电或固件变化后的恢复。旧锁不会自动删除。不同私有目录之间不协调，同一电视只由一名操作者使用同一个状态目录。

## 本地测试与上游

```powershell
$env:PYTHONPATH = 'src'
py -B -m unittest discover -s tests -v
py -B -m webos_locale --help
```

测试只使用人工构造的数据，不连接电视、不要求安装运行依赖。原生守护进程与写入进程的隔离 VM 测试需要本地已有 Node；缺少时明确跳过。模拟通过不等于实机通过。

- [LG Settings Service](https://webostv.developer.lge.com/develop/references/settings-service)：公开 locale 读取文档，不代表官方支持 Root 写入接口。
- [webOS OSE settingsservice](https://github.com/webosose/settingsservice)：实现参考，不能直接代替专有 TV 固件证据。
- [Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel)：既有 Root 执行通道。
- [SlopBro](https://github.com/throwaway96/slopbro)：外部 Root 研究背景；本工具不包含该项目，也不据此承诺 Root 兼容性。

MIT License，保留原有 [LICENSE](LICENSE)。不分发 LG 固件、字体、翻译文件、真实私有备份或第三方源码。安全边界与剩余风险见 [SECURITY.md](SECURITY.md)。
