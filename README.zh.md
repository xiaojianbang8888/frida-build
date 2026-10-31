# Frida 多平台源码构建

这套配置将官方 Frida 17.25.0 源码编译为 Windows、macOS、Android、iOS 和 Linux 的原生组件。只需 Windows 操作 GitHub 网页，Apple 平台使用 GitHub 的 macOS runner。

版本于 2026-10-31 通过官方 GitHub Release API 核对，固定提交为 `f74818ada177756bd95c26235cdd26ebe4f07e76`。版本与工具链配置位于 `frida-version.json`；脚本核对源码提交。`upstream` 配置要求源码干净，`xjb` 配置只接受固定哈希的原始文件或本配置已应用的结果。

## 定制标识构建（xjb）

Actions 的 `profile` 可选择 `upstream`（官方基线）或 `xjb`（定制标识）。两者使用独立源码、构建目录与产物名。`xjb` 的明确修改清单位于 [profiles/xjb.json](profiles/xjb.json)，每个文件记录原始/修改后 SHA-256、替换原文和命中次数；不是不受限制的全局字符串替换。

`xjb` 将原生程序命名为 `xjb-server`、`xjb-inject`、`xjb-portal`，Gadget 命名为 `xjb-gadget`，资产目录为 `lib/xjb-1.0`。它定制线程显示名、部分 helper/agent 临时路径和内部 socket 名，并将私有 agent 入口配套改为 `xjb_agent_main`。Apple Gadget 的安装名称对应 `XjbGadget.dylib`。所有上游许可证和归属信息保留。

此配置以现有 Frida 17.25.0 远程客户端兼容为目标：DBus/RPC 标记、公开 C/JS API、默认端口以及客户端用于发现 Gadget 的线程标记仍是原协议。上游预编译依赖、内嵌 Android helper DEX/Java 包名、SELinux policy 类型、内部资源标识、诊断字符串中还可能出现上游名称。更改文件名不会消除注入行为、可执行映射、内存特征或 hook 修改；不能据此声称“所有特征已去除”或“无法检测”。实际兼容性和检测结果以具体自有/获授权样本的验证为准。

在 Actions 手动运行时选择 `profile=xjb`、`platform=all`；本地启动脚本用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-actions.ps1 -Repository xiaojianbang8888/frida-build -Profile xjb -Platform all
```

本地准备源码：

```powershell
python -u scripts/build.py prepare --profile xjb
```

默认写入 `work/src/17.25.0-xjb`，保留现有 `work/src/17.25.0` 官方源码。构建时同样传入 `--profile xjb`，目录为 `work/17.25.0/xjb/<目标>/`，压缩包为 `xjb-17.25.0-<目标>.tar.xz`。清单记录配置摘要及修改模块的提交。

打包时扫描原生组件中的 9 项指定原始标识（UTF-8、UTF-16LE），结果写入 `identifier_audit`；这项扫描只覆盖列明的字节串。Windows x64、Linux x64、macOS arm64 runner 已对临时自有子进程通过 attach、QuickJS 和 RPC init 测试，报告另存为 `native-smoke-<目标>.json`。Android/iOS 真机验证需设备与授权测试样本。实验记录见 [docs/2026-10-31-source-profile.md](docs/2026-10-31-source-profile.md)。

`xjb` 五个平台共 12 个架构的产物已完成并下载，核对了全部压缩包及 1,837 个包内文件的 SHA-256；12 组清单中的指定标识扫描均无命中。成功产物来自 [首轮的 9 组非 Windows 目标](https://github.com/xiaojianbang8888/frida-build/actions/runs/41174956525)、[Windows 短路径重跑的 2 组](https://github.com/xiaojianbang8888/frida-build/actions/runs/41175721303) 和 [macOS arm64 终端修正重跑](https://github.com/xiaojianbang8888/frida-build/actions/runs/41176831129)。首轮整体显示失败，已解决的路径和测试终端问题保留在实验记录中。

Windows runner 使用 `D:/f` 短构建根，避免 MSVC 兼容架构构建路径超过限制。Apple 平台可用 `apple_target` 选择单个架构重跑，默认 `all`。

| 平台 | 架构 | 构建环境 |
| --- | --- | --- |
| Windows | x86、x86_64 | windows-latest runner，匹配预编译 SDK 的 VS C++ 工具链 |
| macOS | x86_64、arm64 | macOS runner，Xcode |
| Android | arm、arm64、x86、x86_64 | Ubuntu runner，Android NDK r29 |
| iOS 真机 | arm64、arm64e | macOS runner，iPhoneOS SDK |
| Linux | x86_64、arm64 | Frida 官方 x-tools 容器 |

共 12 个构建目标。可以在运行工作流时选择单个平台，或选择 `all`。

## 在 GitHub Actions 中构建

1. 创建 GitHub 仓库，将**本目录的内容放到仓库根目录**。例如工作流路径应为 `.github/workflows/build.yml`，而不是 `frida-build/.github/workflows/build.yml`。使用 Git 推送或上传附带压缩包解压后的文件时，确认隐藏的 `.github` 目录也包含在内。
2. 将这些文件放到仓库默认分支，打开仓库的 **Actions → Build Frida → Run workflow**。
3. 在 `platform` 选择 `windows` 先跑通一组，随后可以选择其他平台或 `all`。
4. 每个成功任务都会在此次运行页面上传对应架构的 Artifact，其中包含 `.tar.xz` 产物、SHA-256 校验文件和 JSON 清单，保留 7 天。失败任务会尝试保存构建日志。

工作流手动触发，使用仓库只读权限；构建不需要 Frida 官方发布流程所用的 AWS、Cloudflare 或 Apple 证书密钥。

## GitHub 登录与启动

可以安装 [GitHub CLI](https://cli.github.com/)，在本目录运行以下 PowerShell 命令，并按终端提示打开浏览器授权。本次操作的 Windows 工作区另已准备便携版，位于 `work/tools/gh/bin/gh.exe`，该二进制未提交到仓库。

```powershell
gh auth login --hostname github.com --git-protocol https --web
```

如使用 fine-grained token，先创建构建仓库，在 GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens** 中生成令牌，仅选择该仓库，授予 **Contents、Workflows、Actions** 的 **Read and write** 权限。令牌应通过 GitHub CLI 本地登录输入；不要放到源码、工作流、命令行参数或聊天中。

文件上传到仓库默认分支后，可以使用以下脚本触发、等待并下载五个平台的构建产物：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-actions.ps1 -Repository 用户名/仓库名
```

脚本需要已登录且有权限运行目标仓库的 Actions。它会触发 `build.yml` 的 `platform=all` 运行，等待结果，将成功产物下载到 `dist/actions/<运行ID>/`，失败时显示失败步骤日志。也可以在 GitHub 网页中手动触发。

## 网络连接

工作流已移除之前的 `192.168.50.13:7897` 代理配置，GitHub 托管 runner 使用默认直连网络。本机直连 GitHub 主站、API、raw 源码以及 `git ls-remote` 已验证通过。

## 产物内容与验证范围

每组产物包含 `frida-server`、`frida-gadget`、`frida-inject`、`frida-portal`，以及 Gum、GumJS、Core 的 C/C++ 开发包。默认保留 Frida 的兼容架构构建逻辑。与官方工作流一致，iOS arm64e 关闭 compiler backend，其他目标启用该组件。

本轮构建范围不包含 Python wheel、Node.js 绑定、`frida-tools` Python 命令行包、iOS 模拟器或 iOS 的 deb 安装包。需要 Python 客户端时，请配套安装 `frida==17.25.0` 和相应的 `frida-tools`。

打包前检查可执行文件和 Gadget 的 PE、ELF 或 Mach-O 架构，以及三个开发包的头文件和静态库。与构建机系统和架构一致时，还会执行 `frida-server --version`。Android、iOS 等目标需要另做设备运行测试；这些检查无法证明真机注入功能已经通过。

压缩包包含每个安装文件的 SHA-256 清单，并附带整包 SHA-256。iOS 使用 `/usr` 安装前缀加 `DESTDIR` 暂存，压缩包中的 `usr/` 需作为整体处理，包括 helper 和 agent。

Apple 构建使用 `MACOS_CERTID=-`、`IOS_CERTID=-` 临时签名。它可以验证编译流程；macOS 分发签名、公证和 iOS 部署所需的签名、权限环境需另行配置。iOS server 的运行条件与将 Gadget 嵌入应用的条件不同。

Linux 采用官方 `ghcr.io/frida/x-tools-linux-<arch>:latest` 容器及其 `XTOOLS_HOST`，以沿用官方工具链的兼容性基线。容器的 `latest` 标签会变化；若要求工具链也严格复现，应在首次成功构建后固定镜像 digest。

## Windows 本地构建

需要 Git、Python、Node.js/npm、新版 VS C++ 工具链和 Windows SDK。VS 工具链必须匹配 Frida 预编译 SDK 的要求；17.25.0 的 V8 依赖在 windows-2022 的 MSVC 14.44 下会缺少标准库链接符号，CI 因此与官方工作流一致使用 windows-latest。启用 compiler backend 还需按 `frida-core/src/compiler/go.mod` 安装 Go（当前要求 1.26），以及 MinGW GCC 提供的 cgo 支持。

在本目录运行 PowerShell；以下使用短路径以减少 Windows 路径长度问题：

```powershell
python -u scripts/build.py prepare --source D:\frida-src\17.25.0

# 改为实际 MSYS2 安装路径；64 位目标安装 UCRT64 GCC，32 位目标安装 MINGW32 GCC。
$env:MSYS2_LOCATION = 'C:\msys64'
python -u scripts/build.py build --target windows-x86_64 --source D:\frida-src\17.25.0 --work-root D:\frida-work
```

构建脚本会使用 Frida 自带的 configure/Make/Meson 入口及预编译依赖包，不需要全局安装 Meson、Ninja 或 Vala。首次运行需要联网下载源码、子模块、依赖工具链和 npm/Go 依赖。

源码保持在 `--source` 指定的位置，各架构的构建目录在 `--work-root/<版本>/<目标>/` 下。默认压缩包输出到本目录 `dist/`。相同配置可以增量重跑；改变配置时请选择新的 `--work-root`。

## 当前验证记录

- 已通过 actionlint 1.7.12 的工作流检查。
- 已通过 Python 语法检查，以及 15 项测试，覆盖打包、架构、源码 profile 的重复应用/意外修改拒绝、配置摘要与指定字节标识扫描。
- 已在公开仓库 [xiaojianbang8888/frida-build](https://github.com/xiaojianbang8888/frida-build) 完成 Windows、macOS、Android、iOS、Linux 共 12 组架构构建。
- [首轮运行](https://github.com/xiaojianbang8888/frida-build/actions/runs/41121484242) 中，macOS、iOS、Android、Linux 的 10 组架构均成功，Windows 两组遇到旧 MSVC 与 V8 依赖不匹配的问题。
- 改用 windows-latest 后，[Windows 重跑](https://github.com/xiaojianbang8888/frida-build/actions/runs/41122665431) 的 x86、x86_64 两组均成功。
- 本轮成功产物分别位于以上两次运行的 Artifacts 中，保留 7 天。macOS arm64、Linux x86_64 和 Windows x86_64 在 runner 上通过了 `frida-server --version` 检查。
- 本轮验证不包含手机真机注入测试，也不包含 macOS 分发签名、公证或 App Store 部署验证。

复查配置可运行：

```powershell
python -m unittest discover -s tests -v
python -m py_compile scripts/build.py tests/test_build.py
```

官方依据：[17.25.0 源码](https://github.com/frida/frida/tree/17.25.0)、[官方构建工作流](https://github.com/frida/frida/blob/17.25.0/.github/workflows/ci.yml)、[稳定版发布](https://github.com/frida/frida/releases/tag/17.25.0)。
