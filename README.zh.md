# Frida 多平台源码构建

这套配置将官方 Frida 17.25.0 源码编译为 Windows、macOS、Android、iOS 和 Linux 的原生组件。只需 Windows 操作 GitHub 网页，Apple 平台使用 GitHub 的 macOS runner。

版本于 2026-10-31 通过官方 GitHub Release API 核对，固定提交为 `f74818ada177756bd95c26235cdd26ebe4f07e76`。版本与工具链配置位于 `frida-version.json`；脚本会核对源码提交并拒绝有修改的源码目录。

| 平台 | 架构 | 构建环境 |
| --- | --- | --- |
| Windows | x86、x86_64 | Windows 2022 runner，VS C++ 工具链 |
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

本机已准备便携版 GitHub CLI，位于 `work/tools/gh/bin/gh.exe`，不需要全局安装。在本目录运行以下 PowerShell 命令，并按终端提示打开浏览器授权：

```powershell
.\work\tools\gh\bin\gh.exe auth login --hostname github.com --git-protocol https --web
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

需要 Git、Python、Node.js/npm、VS 2022 C++ 工具链和 Windows SDK。启用 compiler backend 还需按 `frida-core/src/compiler/go.mod` 安装 Go（当前要求 1.26），以及 MinGW GCC 提供的 cgo 支持。

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
- 已通过 Python 语法检查，以及 7 项打包检查测试：错误架构、缺失组件、缺失开发包、清单与压缩包校验、arm64e 子类型校验、兼容架构 Gadget、Apple 通用二进制。
- 本机直连 GitHub 主站、API、raw 源码以及 `git ls-remote` 已恢复；尚未执行本地编译。
- 尚未触发 GitHub Actions，尚无实际编译成功或设备运行成功的记录。

复查配置可运行：

```powershell
python -m unittest discover -s tests -v
python -m py_compile scripts/build.py tests/test_build.py
```

官方依据：[17.25.0 源码](https://github.com/frida/frida/tree/17.25.0)、[官方构建工作流](https://github.com/frida/frida/blob/17.25.0/.github/workflows/ci.yml)、[稳定版发布](https://github.com/frida/frida/releases/tag/17.25.0)。
