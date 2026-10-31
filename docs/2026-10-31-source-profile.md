# Frida 17.25.0 定制标识实验记录

## 第一轮：官方源码静态检查

- 记录时间：2026-10-31（Asia/Shanghai）。
- 分析思路：在已经完成五个平台、12 个架构的官方构建基线上，区分运行时标识、内部加载契约与客户端协议。源码中出现字符串不等于某个应用实际检测了该字符串，改名也不能证明无法检测。
- 本轮操作：读取构建脚本、工作流、官方 core/gum 源码并检查 Git 状态。
- 操作目的：找出可协调改动的标识，同时保留可复现的官方基线与常规客户端兼容能力。
- 所用工具：PowerShell、Git、ripgrep、Python；技能为 `xiaojianbang-auto-reverse`。没有连接设备或反编译目标二进制。
- 运行命令：在 `work/src/17.25.0` 运行 `git status --short`；使用 `rg -n` 检索 `frida-agent`、`frida_agent_main`、`g_thread_new`、`re.frida`、`frida:rpc`、`27042`。
- 代码变更：本轮只新增实验记录；官方源码未修改。
- 检测代码明细：尚无目标应用或检测代码。下列是已确认的源码标识来源，并非已验证的检测链：

| 来源（均相对 subprojects） | 已确认标识与用途 | 兼容性影响 |
| --- | --- | --- |
| `frida-gum/bindings/gumjs/gumscriptscheduler.c` | `g_thread_new("gum-js-loop", ...)` 创建 JS 线程 | 线程显示名可单独定制 |
| `frida-core/src/frida-glue.c` | `frida-main-loop` | 线程显示名 |
| `frida-core/src/agent-container.vala` | `frida-agent-container` | 线程显示名；同文件查找 agent 入口 |
| `frida-core/lib/agent/agent.vala` | `frida-eternal-agent`、`frida-agent-emulated` | 线程显示名 |
| `frida-core/lib/gadget/gadget-glue.c`、`gadget.vala` | `frida-gadget`、`frida-gadget-tcp-%u`、`frida-gadget-unix` | TCP 线程名还被 fruity injector 识别，修改需配套 |
| `frida-core/server/server.vala` | `re.frida.server` 默认目录、server 主循环名 | 默认目录和线程显示名 |
| `frida-core/src/linux/linux-host-session.vala`、`frida-helper-process.vala` | agent 资源名、helper 临时文件名、Android helper 线程 | 资源使用端与生成端应一致 |
| `frida-core/src/android-helper/client.vala` | helper DEX 路径、Java 类、进程 nice-name、localabstract 地址 | 类名、嵌入 DEX、两端地址必须匹配 |
| `frida-core/lib/agent/meson.build` 与导出列表、各平台 host-session | `frida_agent_main` 导出与符号查找 | 必须同时修改定义、导出和所有加载端 |
| `frida-core/meson.build`、`src/embed-agent.py` | agent/helper/gadget 文件名及内嵌资源 | 必须保持 Meson、资源生成、运行时查找一致 |
| `frida-core/lib/base/session.vala` | `re.frida.HostSession17` 等 DBus 接口 | 现有客户端依赖的协议契约 |
| `frida-core/lib/base/rpc.vala` 与 gumjs runtime | `frida:rpc` 消息标记 | Python/Node 客户端和脚本运行时依赖 |
| `frida-core/lib/base/socket.vala` | 默认控制端口 27042、集群端口 27052 | 客户端默认发现/连接行为依赖，可用配置指定端口 |

- 实验结果：已确认上述源码位置。尚未修改源码、生成定制二进制或验证任何目标检测。官方源固定在 `f74818ada177756bd95c26235cdd26ebe4f07e76`；core 为 `f91556129517937e82831458d10f6b8f4ca06dbb`；gum 为 `5ebe3aeccab8dcd4b727378dab67fb15fa8a3cca`。
- 下一步计划：默认按五个平台、兼容现有客户端创建独立源码配置。用明确文件及原文校验限制修改范围，记录补丁摘要，测试重复准备与拒绝意外改动；再运行构建。行为、映射、依赖库、内存内容与 hook 痕迹需要实际获授权样本验证，不能由字符串改名推断消失。

## 第二轮：独立 xjb 配置与本地校验

- 记录时间：2026-10-31（Asia/Shanghai）。
- 分析思路：优先处理不改变远程客户端协议的明确源码位置；内部 agent 符号必须同时覆盖 Vala 的 CCode 定义、C 调用、导出表和加载端。兼容架构构建的最终文件查找也需随原生产物改名调整。
- 本轮操作：新增 `profiles/xjb.json`、`scripts/source_profile.py`、`scripts/audit_artifacts.py`、`scripts/smoke_native.py`；扩展构建/启动脚本、工作流与测试；另行克隆 `work/src/17.25.0-xjb` 后应用配置并再次准备。
- 操作目的：使修改可检查、可重复、可回退，并让打包清单记录配置摘要；避免将改名直接描述为绕过检测。
- 所用工具：Python 3.13（本机）、Git、ripgrep、actionlint 1.7.12；CI 使用已固定的 Python 版本。
- 运行命令：`python work/create_xjb_profile.py`（仅生成明确文本文件的配置，不修改源码）；`python -u scripts/build.py prepare --profile xjb`（两次）；`python -m unittest discover -s tests -v`；`python -m py_compile scripts/build.py scripts/source_profile.py scripts/audit_artifacts.py scripts/smoke_native.py`；`work/tools/actionlint/actionlint.exe .github/workflows/build.yml`；`git diff --check`；检查独立源码的 `git diff` 及官方源码的 `git status --short`。
- 代码变更：core 的 48 个文本文件与 gum 的 6 个文本文件，完整替换原文、次数和哈希位于 `profiles/xjb.json`。源码 profile 摘要为 `440abfbcd78d250d47f797698b9ed43c2b258a1aa21419b4a542a058d6c0d730`。前期生成清单发现上游测试目录还含有带同名符号的二进制 fixture，因此生成器使用 `git grep -Il` 排除二进制；未对二进制 fixture 做替换。
- 检测代码明细：未提供目标检测样本，未确认检测函数或退出分支。修改为本记录第一轮列出标识中的明确子集。保留客户端协议、Gadget 的 TCP/UNIX 发现线程名、预编译 Android helper DEX/包名、SELinux `frida_memfd` policy 类型与内部嵌入资源 ID。选定的 9 项原始字节标记由打包审计分别检查 UTF-8 和 UTF-16LE；不把该审计解释为全部特征检查。
- 实验结果：15 项本地单元测试、Python 语法检查和 actionlint 通过；独立源码重复准备通过；官方源码 Git 状态干净。补丁已经应用到独立源码，尚无定制二进制编译或真机测试结果。
- 下一步计划：运行五个平台 12 架构构建，在可运行的三个原生 runner 上执行临时自有进程的 attach、QuickJS 和 RPC init 验证；下载产物并核对哈希。Android/iOS 仍需设备与获授权检测样本。

## 第三轮：Windows CI 路径长度修正

- 记录时间：2026-10-31 14:10 后（Asia/Shanghai）。
- 分析思路：根据首个失败任务定位编译器报错；区分源码修改错误、资源契约错误和 Windows 路径限制。
- 本轮操作：读取 Actions 运行 `41174956525` 的 Windows x64 job `124460516582` 日志；计算错误路径与工作目录组合后的长度；将 Windows CI 的源码和构建根改为 `D:/f`，并同步 Go 配置和诊断日志路径。
- 操作目的：修复新增独立配置目录使 MSVC 编译路径超过旧限制的问题。
- 所用工具：GitHub CLI、PowerShell、Python PureWindowsPath。
- 运行命令：`gh api --allow-escape-sequences repos/xiaojianbang8888/frida-build/actions/jobs/124460516582/logs`（日志保存于 `work/xjb-windows-initial.log`）；检索 `fatal error`、`ERROR:`；计算 cwd 与相对源路径拼接长度。
- 代码变更：`scripts/build.py` 读取可选 `FRIDA_BUILD_ROOT`；`scripts/smoke_native.py` 使用同一根目录；Windows job 设置 `FRIDA_BUILD_ROOT=D:/f` 并调整 setup-go 与日志上传。源码 profile 内容及摘要不变。
- 检测代码明细：无新目标检测证据；本轮是构建错误，与目标应用检测无关。
- 实验结果：失败点为兼容 x86 Gum 的 `gummemoryaccessmonitor-windows.c`，MSVC 报 C1083；未规范化的组合路径长 263 字符。其他平台仍在编译，Windows 短路径修正待重跑验证。
- 下一步计划：本地校验更改后单独启动 Windows 构建，继续跟进其余平台。

## 第四轮：首批验证与 macOS 测试终端修正

- 记录时间：2026-10-31 14:27 后（Asia/Shanghai）。
- 分析思路：根据原生测试日志判断失败发生阶段，避免把测试终端问题误记为目标检测或 agent 错误。
- 本轮操作：读取 Linux x64 与 macOS arm64 的任务日志；对已下载 Android x86 的 server/Gadget 与官方基线做指定字节串对照；将 POSIX 测试输入改为伪终端，增加 Apple 单架构重跑选择。
- 操作目的：验证定制入口和 RPC，同时修复原生 inject 工具在 macOS `/dev/null` 输入上的终端初始化错误。
- 所用工具：GitHub CLI、Python tarfile、指定标识扫描、POSIX PTY。
- 运行命令：读取 job `124460516598`（`work/xjb-linux-x64.log`）及 `124460516667`（`work/xjb-macos-arm64-initial.log`）的日志；`python work/compare_identifiers.py`。
- 代码变更：`scripts/smoke_native.py` 在 POSIX 上以 `os.openpty()` 分配测试 stdin；工作流与启动脚本允许 `apple_target=macos-arm64`，方便只重跑该目标。源码 profile 与摘要不变。
- 检测代码明细：仍无目标应用检测证据。Android x86 基线的 server/Gadget 实际命中所选 9 项中的 8 项原始标识，定制二进制为 0；对照范围详见本地产物目录的 `identifier-comparison-android-x86.json`，不推断其他特征消失。
- 实验结果：Android 四架构、iOS 两架构、Linux 两架构成功。Linux x64 原生测试输出 `XJB_RPC_SMOKE={"pid":8347,"arch":"x64","modules":12,"runtime":"QJS"}`，attach、脚本加载、RPC init/回复通过。macOS arm64 编译和打包通过，随后测试输出 `tcgetattr failed: Operation not supported by device` 并以 4 退出，未宣称该平台运行测试成功。Windows 初轮 x86 也遇到同一 C1083 路径错误；短路径重跑的 x86 已成功，x64 尚在进行。
- 下一步计划：单独重跑 macOS arm64，继续下载并核对各平台产物与原生测试报告。
