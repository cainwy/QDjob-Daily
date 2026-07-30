# QDjob-Daily

QDjob 定时任务方案，每日自动拉取最新 QDjob 程序、获取隐私配置、在临时隔离目录中执行任务并将日志回传。

## 工作流程

```
每日 08:30 (北京时间)
   ↓ 随机延迟 0-5 分钟
拉取 QDjob 最新 Release 并与 .qdjob_version 比较

   ┌─── 新版本 或 版本分支缺失？ ───┐
   │                                ↓
   │                    从 Release 下载 QDjob
   │                    创建版本分支 提交 QDjob 二进制
   │                    更新 main 的 .qdjob_version
   │                                │
   └──────── 版本一致且分支存在 ─────┘
                    ↓
           从版本分支 git archive 提取 QDjob
                    ↓
          创建临时目录 /tmp/qdjob-run/
          ├── 放入 QDjob 可执行文件
          └── 克隆数据仓库并复制数据
                    ↓
               执行 QDjob
                    ↓
         将生成的 logs/ 推送到数据仓库
         调用extract_logs.py对日志进行处理, 并将结果推送到TG

   ┌─── workflow-keepalive ───┐
   │ 防止 60 天无提交后       │
   │ 自动停用定时任务          │
   └──────────────────────────┘
```

## 仓库结构

```
QDjob-Daily/
├── .qdjob_version              # 主分支：当前 QDjob 版本记录
├── README.md
├── extract_logs.py             # 日志处理
└── .github/workflows/
    └── qdjob-daily.yml         # Action 工作流

版本分支（如 QDjob_v1.3.6）仅包含：
  ├── QDjob                     # QDjob 可执行文件
  ├── QDjob_editor
  └── ...

运行时临时目录 /tmp/qdjob-run/（不提交）：
  ├── QDjob                     # QDjob 可执行文件
  ├── config.json               # 从数据仓库复制来的配置
  ├── cookies/
  └── logs/                     # 运行生成的日志 → 推送到数据仓库
```

## 快速开始

### 1. 准备数据仓库

创建一个**私有**仓库（如 `QDjob-Data`），将 `config.json` 等配置文件放入根目录：

```
QDjob-Data/
├── config.json
└── cookies/
    └──...
```

### 2. Fork 本仓库

```bash
git clone https://github.com/2061360308/QDjob-Daily.git
```

### 3. 创建 Fine-grained Personal Access Token

访问 [GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens](https://github.com/settings/tokens?type=beta)

1. 点击 **Generate new token**
2. **Repository access** 选择 **Only select repositories**，选中你的私有数据仓库
3. **Permissions** 设置：
   - `Contents` → **Read and write**
4. 生成后复制 token（格式：`github_pat_xxx`）

### 4. 配置 Action Secret

在你的 `QDjob-Daily` 仓库中：

1. **Settings** → **Secrets and variables** → **Actions**
2. 点击 **New repository secret**
3. Name: `DATA_REPO_TOKEN`;`BOTTOKEN`;`CHATID`
4. Secret: 粘贴上一步生成的 token; bot的token; chat ID
5. 点击 **Add secret**

### 5. 修改工作流配置

编辑 `.github/workflows/qdjob-daily.yml`，文件顶部的 `env` 区域集中管理所有可配置项：

```yaml
env:
  QDJOB_REPO:        qdjob/QDjob                    # QDjob 发布仓库
  QDJOB_ASSET:       QDjob_linux_amd64.zip          # 下载的资产文件名
  DATA_REPO:         2061360308/QDjob-Data          # 改为你的数据仓库
  GIT_USER:          github-actions[bot]
  GIT_EMAIL:         github-actions[bot]@users.noreply.github.com
```

只需将 `DATA_REPO` 改为 `你的用户名/你的数据仓库` 即可，无需在脚本内部修改。

如果不需要TG通知,删除下面的内容:
```yaml
      - name: Extract logs and notify via Telegram
        if: always()
        env:
          BOTTOKEN: ${{ secrets.BOTTOKEN }}
          CHATID: ${{ secrets.CHATID }}
        run: |
          python extract_logs.py /tmp/qdjob-run/logs/qidian.log \
            --today-only \
            --send \
            --bot-token "$BOTTOKEN" \
            --chat-id "$CHATID"
```

### 6. 触发运行

推送后自动部署，也可以手动触发：

- **自动**：每日北京时间 08:30 自动执行（含随机延迟 0-5 分钟）
- **手动**：Actions 页面 → QDjob Daily → Run workflow
