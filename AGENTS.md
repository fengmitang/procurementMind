# 项目环境记忆

## Python 环境

- 本机 Anaconda 安装目录：`F:\Anaconda`
- 本项目使用的 Conda 环境：`purchasing-agent`
- 环境目录：`F:\Anaconda\envs\purchasing-agent`
- Python 可执行文件：`F:\Anaconda\envs\purchasing-agent\python.exe`
- 已确认的 Python 版本：Python 3.12.13（Anaconda）
- 本项目后续所有 Python 依赖安装、升级、卸载及其他环境配置变更，都必须作用于 `purchasing-agent` 环境。


## Git 与 GitHub

- 目标远端仓库：`https://github.com/fengmitang/procurementMind.git`
- GitHub 仓库：`fengmitang/procurementMind`
- 默认分支：`main`
- 仓库已经包含采购业务后端、测试、前端体验页面和部署配置。
- 本机 Git for Windows 默认 OpenSSL 通道连接 GitHub 失败；使用 Windows `schannel` 后已验证可以连接。
- 初始化本地仓库后，应设置仓库级配置：`git config http.sslBackend schannel`
- 当前 GitHub 连接已确认具有该仓库的推送权限。
- 本地开发完成后，需要将代码推送到上述仓库。

## 当前项目目录

- 本地项目目录：`F:\Studio\ProcumentMind`
- 当前目录已经初始化为 Git 仓库，并跟踪远端 `main` 分支。

## MySQL

- 数据库连接配置保存在项目根目录的 `.env` 中，且 `.env` 已加入 `.gitignore`。
- 数据库地址：`127.0.0.1:3306`
- 数据库名称：`procurement_mind`
- 数据库用户：`root`
- 已确认的 MySQL 版本：MySQL 8.0.44
- 已在 `purchasing-agent` 环境安装 `PyMySQL 1.2.0`。
- 截至 2026-07-29，已验证数据库连接正常，数据库内有 0 张表。
- 不要在代码、文档、日志或 Git 提交中记录数据库密码。
