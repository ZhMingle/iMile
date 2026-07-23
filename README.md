# iMile Daily Report Automation

## Sending Mode Quick Reference

Use the explicit shortcut scripts to avoid duplicate sending:

```powershell
.\daily_webhook.bat   # Full daily workflow, send through existing webhooks / bots
.\daily_as_me.bat     # Full daily workflow, send as your own Feishu/Lark account
.\send_as_me.bat      # Send configured user-identity images only, without rebuilding reports
```

The old `run_daily_report.bat` entry has been removed because it was too easy to send through more than one delivery mode by mistake.

`run_daily_report.py` and `send_lark_images.py` default to webhook-only sending. User-identity sending happens only when you explicitly use `--send-as user` or one of the `*_as_me.bat` shortcuts.

### Delivery Modes

In `lark_config.json`, each message chooses one delivery mode:

```json
{
  "name": "Supplier group",
  "send_as": "webhook",
  "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/...",
  "secret": "",
  "image": "output/supplier/Click'N Code.png"
}
```

```json
{
  "name": "Management group - send as me",
  "send_as": "user",
  "receive_id_type": "chat_id",
  "receive_id": "oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "image": "output/supplier/Click'N Code.png"
}
```

For Feishu China, keep these top-level config fields:

```json
{
  "open_platform_domain": "open.feishu.cn",
  "redirect_uri": "http://localhost:8765/callback",
  "user_scope": "im:message im:message.send_as_user im:message:recall"
}
```

The redirect URL must be added in the Feishu Developer Console. The app also needs the user permissions `im:message` and `im:message.send_as_user` for personal-account sending. To recall API-sent messages, also enable `im:message:recall`.

## 中文说明

### 项目目的

这个项目用于自动化 iMile 每日到件统计和飞书分发流程。实际业务里，最原始的数据来自订单明细，例如 Temu/清关公司文件、菜鸟邮件附件等；这些订单明细会先被整理成查询单号，再到内部系统查询得到“中心运单查询”数据。最后，脚本会把中心运单查询结果写入 `当日数据统计.xlsx`，生成最终想要的统计结果和飞书图片。

以前这些步骤需要手动复制单号、粘贴到内部系统查询、再把统计结果和截图复制粘贴到不同飞书群。这个项目把后半段重复操作自动化：

- 从 `input/` 的原始订单明细中提取查询单号
- 自动把查询单号提交到内部系统并下载“中心运单查询”文件
- 按明确列出的 Route Code 合并箱号，并为唯一箱号精确选中指定司机
- 用“中心运单查询”文件更新 `当日数据统计.xlsx`
- 生成供应商分单、非奥克兰总览和线路预测图片
- 按飞书配置把图片发送到对应群

项目适合每天重复使用，减少人工统计、截图和逐群复制粘贴图片的工作量。

### 企业微信自动收件（Windows）

Windows 版「iMile 报表助手」顶部提供“自动收件”按钮。日常主流程使用 `iMile x WISEWAY`；
`iMile x Auslink TEMU handover` 仅作为偶发顺友货的备用入口。用户手动打开对应企业微信群后，
程序用本地 OCR 识别当前群和当前画面。WISEWAY 群从 `Temu:` 与 `Cainiao:` 区段提取主单号：
TEMU 文件从企业微信缓存或聊天记录下载到 `input/TEMU/日期/`，Cainiao 文件从 Lark 邮箱下载
到 `input/CAINIAO/日期/`。Auslink 顺友群会提取画面中的主单号，在 Lark 邮箱中只选择
`IMILE末端预报` Excel 附件，排除同邮件的 MAWB PDF，重命名为 `顺友{8位单号}.xlsx` 并归档到
`input/SHUNYOU/日期/`。

首次使用：

1. 安装并登录企业微信 Windows 客户端。
2. 在助手中点击“收件设置”。
3. 在 `wecom_download_config.json` 中填写准确的 `chat_name` 和 `shunyou_chat_name`。
4. 日常手动打开 WISEWAY 主群；仅有顺友货时打开 Auslink 备用群，并让完整数据消息显示在当前画面。
5. 在 Lark 桌面端打开邮箱收件箱，让“搜索邮件”输入框显示。
6. 在浏览器登录 iMile DC 系统。
7. 回到助手点击“自动收件”。

程序会先检查企业微信登录状态和当前群名；未登录、群名不符或无法确认时会停止并提示用户。
收件只处理当天发送的数据消息；发送者、发送时间和完整消息必须同时在当前画面可见。画面中若
只有昨天或更早的消息，程序会停止并显示识别到的日期，不会沿用旧单号下载。
自动化只在 OCR 同时确认“聊天记录”页面标志后，才会在记录搜索框输入 8 位数字并点击文件
卡片。Cainiao 自动化只在同时识别到“邮箱 / 收件箱 / 搜索邮件”后才会搜索邮件和点击附件，
并通过附件右键菜单的“下载”文字确认下载动作，不会进入写邮件界面。所有点击位置都根据
当前窗口截图动态计算，支持窗口化、全屏和不同 Windows 缩放比例，不依赖固定屏幕坐标。
程序不会切换或搜索群聊，不会操作聊天输入框，也没有发送消息步骤。

附件先保存到 Windows 当前用户真实的“下载”系统目录下，每票使用独立临时目录，因此同名
附件不会覆盖；最终归档路径相对程序目录，整个发布文件夹复制到另一台电脑即可使用。收件
完整后会显示识别票数、成功票数和单号清单，只有用户确认后才继续生成查询单号；缺票时不
会继续。确认后，程序会自动打开固定的“中心运单查询”网址；如果页面没有收藏，则使用左侧
搜索入口按名称进入，不依赖收藏或固定坐标。DC 系统未登录时会提示登录并暂停。查询提交后
程序创建导出任务、轮询进度，完成后点击任务卡片内的下载图标并确认数据安全提示。默认最长
等待 900 秒。DC 页面为中文或英文都可以，程序会识别两种语言的查询、导出和下载控件；英文
导出列名会自动转换为统计脚本使用的中文标准列名。文件校验通过后才会更新项目根目录的
`中心运单查询.xlsx`。

“③ 重试中心运单导出”只使用已有的 `output/query_list.txt`，适合登录补全、网络中断或导出
超时后继续，不会重新读取群消息。DC 自动化使用 Windows UI Automation 按控件名称和页面
结构定位；运行时会把浏览器窗口最大化以显示完整控件，但不依赖电脑分辨率、窗口原始大小或
屏幕坐标。

配置示例见 `wecom_download_config.example.json`。该功能使用屏幕 OCR，企业微信界面升级后
可能需要重新适配；如果没有识别到单号，请确认完整的待处理消息在当前画面中可见。任何
页面校验失败都会立即停止，不会继续点击或输入。

### 自动分单（Windows）

Windows 桌面助手支持按 Route Code 自动完成“查询、逐行选择、合并箱号、分配司机”。使用前请先
在浏览器登录 iMile DC，然后把分单清单直接粘贴进助手的大输入框。每行是一组任务：开头可以有
一个或多个线路，剩余文字是司机姓名。例如下面这份清单可以原样粘贴：

```text
201 Yang Jun
302 303 宋修丞
401 冯卫周3
406 冯卫周2
604 吴良梅
606 吴良梅2
605 冯卫周
404 404B 404S 戴女士
202 301 Travis
```

清单中的字母后缀要紧贴数字填写。程序会自动把 `404B`、`404S` 规范化为网页查询需要的
`404 B`、`404 S`。只填司机姓名时选择搜索结果第一项；需要锁定具体司机时，可以在该行末尾填写
`完整姓名 | 司机ID`。

程序只会勾选输入框中明确列出的 Route Code，不会自行扩展同一基础码的其它字母后缀。例如输入
`404, 404 B, 404 S` 时，即使搜索结果包含 `404 A` 也不会勾选；输入
`501, 501 A, 501 D` 时不会勾选 `501 C`。同一基础线路会用基础码查询；像
`309, 310, 311, 312` 这样的不同线路组合会用安全的共同前缀 `3` 查询，再只勾选明确列出的代码。程序
始终逐行精确核对，不使用表头的“全选”复选框，也不会误选 `4040` 或 `1404`。

选择完成后，程序点击“合并箱号”并等待页面状态稳定，再从刷新后的结果中重新读取箱号。只有
结果收敛为一个唯一箱号时才会继续打开“分配”；不会沿用合并前缓存的箱号。只填司机姓名时，
程序选择搜索结果中页面显示的第一项；填写 `姓名 | 司机ID` 时则必须精确匹配姓名和 ID。没有唯一
箱号、页面未按预期刷新或任何控件状态无法确认时，程序会立即停止。单组任务选好司机后停留在
分配弹窗；批量任务也绝不会点击最终“确定”，而是等待操作人核对并手动确认。确认成功且目标箱号
已从“待分配”移除后，程序才自动查询下一组；如果点击取消或分配未成功，整个队列停止。

程序会优先复用 Edge 中已经打开的 DS“分箱预分配”标签页；只有遍历所有 Edge 窗口仍找不到时才会
新开一个页面，不会因识别到错误窗口而连续创建重复标签。运行后会先切换到“待分配”页签，并确认
Boxcode / 运单数表格已经出现。相关超时配置如下：

- `dc_dispatch_page_timeout_seconds`：等待“分箱预分配”页面可操作，默认 60 秒
- `dc_dispatch_query_timeout_seconds`：等待 Route Code 查询结果完整稳定，默认 45 秒
- `dc_dispatch_action_timeout_seconds`：等待查询、弹窗、司机选项及分配结果，默认 20 秒
- `dc_dispatch_merge_timeout_seconds`：等待合并结果收敛为唯一箱号，默认 60 秒
- `dc_dispatch_manual_confirm_timeout_seconds`：批量任务等待人工点击“确定”，默认 900 秒

### 目录结构

```text
.
├── input/                  # 放原始订单明细 Excel 文件，内容不提交到 Git
├── output/                 # 生成图片和查询列表，内容不提交到 Git
├── 当日数据统计.xlsx        # 主报表模板/结果文件
├── update_report_data.py   # 更新主报表数据
├── build_message_pack.py   # 生成飞书发送用 PNG 图片
├── send_lark_images.py     # 发送图片到飞书
├── run_daily_report.py     # 一键执行更新、生成、发送
├── daily_webhook.bat       # 一键日报，用 webhook / 机器人发送
├── daily_as_me.bat         # 一键日报，用个人账号发送
├── send_as_me.bat          # 只发送个人账号测试消息
├── getTrakingNum.py        # 从 input 文件提取单号到 txt
├── lark_config.json        # 本地真实飞书配置，不提交到 Git
└── lark_config.example.json# 飞书配置模板
```

`input/` 和 `output/` 文件夹会保留在 Git 中，但里面的数据文件会被忽略，只保留 `.gitkeep`。

### 数据格式

#### 原始订单明细：input 文件夹

`input/` 中放最原始的订单明细文件，例如：

- Temu / 清关公司提供的订单明细
- 菜鸟邮件附件
- 其它供应商或渠道导出的 `.xls` / `.xlsx` 明细

`getTrakingNum.py` 会从这些文件中查找列名包含以下关键词的列：

```text
TrackingNo
BillNumber
```

提取后的唯一单号会写入：

```text
output/query_list.txt
```

同时会复制到剪贴板。这个列表用于到内部系统批量查询运单信息。

#### 中心运单查询文件

中心运单查询文件不是最原始数据，而是通过 `output/query_list.txt` 里的单号，在内部系统查询后导出的结果文件。Windows 助手会自动完成查询、导出、等待和下载，并保存为项目根目录的 `中心运单查询.xlsx`。

文件名需要匹配：

```text
*中心运单查询*.xlsx
```

脚本会自动选择最新且列名完整的文件。必须包含以下列：

```text
运单号
路由码
派件网点简码
商家编号
```

常见派件网点简码包括：

```text
AKL, HMT, TRG, WLTV2, NPL, PMN, TPO, RTR, WGR, HST
```

其中：

- `AKL` 用于奥克兰分单统计
- 非 `AKL` 用于非奥克兰到件货量统计
- `商家编号` 用于区分 TEMU、菜鸟、顺友等渠道；菜鸟相关统计按菜鸟商家编号计算，不再按运单号 `36` 开头猜测

#### 最终结果文件

`当日数据统计.xlsx` 是最终想要维护和使用的统计结果。脚本会把中心运单查询数据写入这个工作簿，并更新奥克兰分单、非奥克兰到件货量、线路预测和总量拆分。

### 使用方法

#### 1. 准备数据

将 Temu/清关公司、菜鸟邮件等原始订单明细放入：

```text
input/
```

生成查询单号：

```powershell
python getTrakingNum.py
```

Windows 也可以直接双击 `getTrakingNum.bat`，完成后窗口会显示结果并保留；脚本会自动选择已安装所需 Excel 依赖的 Python。

Windows 助手可点击“③ 重试中心运单导出”，自动读取 `output/query_list.txt` 并生成：

```text
中心运单查询.xlsx
```

命令行仍可只生成查询单号；在非 Windows 环境下需要手动到内部系统导出中心运单查询文件。

#### 2. 配置飞书

复制配置模板：

```powershell
copy lark_config.example.json lark_config.json
```

然后在 `lark_config.json` 中填写真实的：

```text
app_id
app_secret
open_platform_domain
redirect_uri
user_scope
webhook（webhook 消息）
receive_id_type + receive_id（app/user 消息）
```

`lark_config.json` 已被 `.gitignore` 忽略，不会提交到 Git。

`send_as` 决定每条消息的发送方式：

- `webhook`：走原来的 webhook / 机器人。
- `user`：用你自己的飞书账号发送。第一次运行会打开授权页，授权后脚本会把 `user_refresh_token` 写入 `lark_config.json`。
- `app`：用应用机器人身份发送。

中国版飞书使用：

```json
{
  "open_platform_domain": "open.feishu.cn",
  "redirect_uri": "http://localhost:8765/callback",
  "user_scope": "im:message im:message.send_as_user im:message:recall"
}
```

`redirect_uri` 需要在飞书开放平台后台登记。个人账号发送需要用户身份权限 `im:message` 和 `im:message.send_as_user`；撤回 API 发送的消息还需要 `im:message:recall`。

#### 3. 一键运行日报流程

Webhook / 机器人发送：

```powershell
.\daily_webhook.bat
```

个人账号发送：

```powershell
.\daily_as_me.bat
```

也可以直接指定发送方式：

```powershell
python run_daily_report.py --send-as webhook
python run_daily_report.py --send-as user
```

执行顺序是：

```text
1. update_report_data.py
2. build_message_pack.py
3. send_lark_images.py --send --send-as webhook/user
```

#### 4. 只更新主报表

```powershell
python update_report_data.py
```

输出文件：

```text
当日数据统计.xlsx
```

#### 5. 只生成图片

```powershell
python build_message_pack.py
```

生成图片位置：

```text
output/supplier/
output/province/
```

这个脚本现在只生成 PNG 图片，不再生成 CSV 或 TXT。

#### 6. 只发送图片

```powershell
python send_lark_images.py --send
```

默认只走 webhook / 机器人。只用个人账号发送：

```powershell
.\send_as_me.bat
```

或者：

```powershell
python send_lark_images.py --send --send-as user
```

如果遇到飞书限流，可以增加发送间隔：

```powershell
python send_lark_images.py --send --delay 5
```

脚本遇到飞书限流 `11232` 时会自动等待并重试。

#### 7. 撤回 API 发送的消息

`app` 或 `user` 方式发送成功后，脚本会把飞书返回的 `message_id` 自动记录到：

```text
output/sent_messages.jsonl
```

用户授权 token 会缓存到 `output/lark_user_token.json`，避免连续撤回时每条消息都重新打开授权页。`output/` 已被 `.gitignore` 忽略，不会提交这些本地 token。

撤回最近一条个人账号发送的消息：

```powershell
python send_lark_images.py --recall-last --send-as user
```

撤回最近 3 条个人账号发送的消息：

```powershell
python send_lark_images.py --recall-last 3 --send-as user
```

指定 `message_id` 撤回：

```powershell
python send_lark_images.py --recall-message om_xxxxxxxxx --send-as user
```

Webhook 发送的消息不会记录可撤回的 `message_id`，所以这套撤回命令只适用于 `app` / `user` API 发送方式。

#### 7. 生成查询单号文本

```powershell
python getTrakingNum.py
```

#### 8. 使用网页版提取单号

网页版目前只包含 `getTrakingNum` 功能：上传 `.xls` / `.xlsx` 文件后，点击按钮会自动提取并复制单号。

```powershell
cd web
npm install
npm run dev
```

打开终端显示的本地地址，例如：

```text
http://127.0.0.1:5173/
```

输出：

```text
output/query_list.txt
```

### 输出内容

#### 供应商图片

生成在：

```text
output/supplier/
```

示例：

```text
Feng.png
SAFE.png
EMPIRE COURIER.png
```

#### 非奥克兰和线路预测图片

生成在：

```text
output/province/
```

示例：

```text
非奥克兰总览.png
HMT各线路预测.png
TRG各线路预测.png
PMN各线路预测.png
TPO各线路预测.png
NPL_HST各线路预测.png
```

### 注意事项

- 打开中的 Excel 文件可能会被锁定，脚本无法覆盖保存。
- `input/` 和 `output/` 里的文件不会提交到 Git。
- `lark_config.json` 里包含敏感信息，不要提交。
- 飞书同一个群连续发送多张图片可能触发限流，建议不同供应商图片发送到不同群，或者增加 `--delay`。
- 如果 Excel 公式刚被 Python 写入，Excel 打开后会自动重算；图片生成脚本对部分公式统计做了兜底，不依赖 Excel 缓存。

---

## English

### Purpose

This project automates the daily iMile inbound parcel reporting and Lark distribution workflow. In the real workflow, the raw data starts from order detail files such as Temu/customs clearance company files, Cainiao email attachments, and other channel exports. Those raw order details are converted into a query list, then queried in the internal system to produce the center waybill query workbook. Finally, this project updates `当日数据统计.xlsx`, generates the final report images, and sends them to Lark groups.

Previously, the process required manually copying tracking numbers, querying the internal system, updating the workbook, taking screenshots, and pasting images into different Lark groups. This project automates the repetitive reporting and sending steps:

- Extract query numbers from raw order detail files in `input/`
- Merge boxes for explicitly listed Route Codes and select the exact driver for the unique resulting box
- Update `当日数据统计.xlsx` using the internal-system center waybill query export
- Generate supplier dispatch, non-Auckland overview, and route forecast images
- Send images to configured Lark groups

### Automatic Dispatch (Windows)

The Windows desktop assistant can automate the Route Code workflow: query, select each matching row,
merge box numbers, and assign the result to a driver. Sign in to iMile DC, then paste the dispatch list into
the assistant's single multiline field. Each line is one task: one or more leading routes followed by the
driver name. This list can be pasted unchanged:

```text
201 Yang Jun
302 303 宋修丞
401 冯卫周3
406 冯卫周2
604 吴良梅
606 吴良梅2
605 冯卫周
404 404B 404S 戴女士
202 301 Travis
```

Write letter suffixes without an internal space in the pasted list. The assistant normalizes `404B` and
`404S` to the page's required `404 B` and `404 S` format. A name-only driver entry selects the first displayed
search result. Append `Full Name | Driver ID` when exact name-and-ID matching is required.

The assistant checks only Route Codes explicitly listed in the input; it never guesses other letter suffixes.
For `404, 404 B, 404 S`, a `404 A` search result is left unchecked. For `501, 501 A, 501 D`, a
`501 C` result is left unchecked. Codes from one family use their shared base query. A mixed list such as
`309, 310, 311, 312` uses the safe common prefix `3` and then checks only those exact codes. Rows are
always compared exactly and checked individually; the table header's select-all checkbox is not used, and
values such as `4040` or `1404` are not selected.

After selection, the assistant invokes **Merge box numbers**, waits for the page state to settle, and reads
the box number again from the refreshed results. It opens **Assign** only when the result has converged to
one unique box number; it never reuses a box number cached before the merge. For a name-only driver entry,
the assistant selects the first result displayed by the page. Supplying `Name | Driver ID` requires an exact
name-and-ID match. If the merged result is not unique, the page does not refresh as expected, or a control
state cannot be verified, the assistant stops immediately. It never clicks the final **Confirm** button. For
a batch, it waits for the operator to confirm each dialog and verifies that the box has left **Pending
assignment** before proceeding to the next group. Cancelled or unsuccessful assignment stops the queue.

The assistant first reuses an existing DS **Box Pre-allocation** tab found across all Edge windows. It opens
one new page only when no existing tab can be found, preventing repeated duplicates caused by binding to the
wrong window. It then switches to **Pending assignment** and confirms that the Boxcode / waybill-count table
is visible. Dispatch timeout settings are:

- `dc_dispatch_page_timeout_seconds`: wait for the Box Pre-allocation page to become usable; default 60 seconds
- `dc_dispatch_query_timeout_seconds`: wait for Route Code results to become complete and stable; default 45 seconds
- `dc_dispatch_action_timeout_seconds`: wait for queries, dialogs, driver options, and assignment results; default 20 seconds
- `dc_dispatch_merge_timeout_seconds`: wait for the merge result to converge to one box number; default 60 seconds
- `dc_dispatch_manual_confirm_timeout_seconds`: wait for a manual batch confirmation; default 900 seconds

### Project Structure

```text
.
├── input/                  # Raw order detail Excel files; contents ignored by Git
├── output/                 # Generated images and query list; contents ignored by Git
├── 当日数据统计.xlsx        # Main report workbook
├── update_report_data.py   # Updates the main report workbook
├── build_message_pack.py   # Generates PNG images for Lark
├── send_lark_images.py     # Sends images to Lark
├── run_daily_report.py     # Runs update, image generation, and sending
├── daily_webhook.bat       # Runs full workflow and sends with webhooks
├── daily_as_me.bat         # Runs full workflow and sends as your own account
├── send_as_me.bat          # Sends user-identity images only
├── getTrakingNum.py        # Extracts tracking numbers from input files
├── lark_config.json        # Real local Lark config; ignored by Git
└── lark_config.example.json# Lark config template
```

The `input/` and `output/` directories are kept in Git with `.gitkeep`, but their generated or downloaded contents are ignored.

### Data Format

#### Raw order details: input folder

Place the original order detail files in:

```text
input/
```

Typical sources include:

- Temu / customs clearance company order details
- Cainiao email attachments
- Other supplier or channel `.xls` / `.xlsx` exports

`getTrakingNum.py` looks for columns whose names include:

```text
TrackingNo
BillNumber
```

Unique values are written to:

```text
output/query_list.txt
```

They are also copied to the clipboard. Use this list to query waybill information in the internal system.

#### Center waybill query workbook

The center waybill query workbook is not the raw source data. It is the internal-system export produced after querying the tracking numbers from `output/query_list.txt`.

The source workbook name must match:

```text
*中心运单查询*.xlsx
```

The script picks the latest valid workbook. Required columns:

```text
运单号
路由码
派件网点简码
商家编号
```

Common station codes:

```text
AKL, HMT, TRG, WLTV2, NPL, PMN, TPO, RTR, WGR, HST
```

Rules:

- `AKL` is used for Auckland dispatch statistics
- Non-`AKL` rows are used for non-Auckland inbound statistics
- `商家编号` / merchant ID is used to distinguish TEMU, Cainiao, Sunyou, and other channels. Cainiao-related metrics are calculated by Cainiao merchant ID, no longer by guessing from waybill numbers starting with `36`.

#### Final result workbook

`当日数据统计.xlsx` is the final workbook this project maintains. The script writes the center waybill query data into this workbook and updates Auckland dispatch, non-Auckland inbound volume, route forecasts, and total breakdowns.

### Usage

#### 1. Prepare source files

Put Temu/customs clearance company, Cainiao email, or other raw order detail files under:

```text
input/
```

Generate the query list:

```powershell
python getTrakingNum.py
```

Use `output/query_list.txt` to query the internal system, then export the center waybill query workbook and place it in the project root, for example:

```text
中心运单查询 (3).xlsx
```

#### 2. Configure Lark

Copy the example config:

```powershell
copy lark_config.example.json lark_config.json
```

Then fill in real values in `lark_config.json`:

```text
app_id
app_secret
open_platform_domain
redirect_uri
user_scope
webhook for webhook messages
receive_id_type + receive_id for app/user messages
```

`lark_config.json` is ignored by Git.

Use `send_as` per message:

- `webhook`: send through the existing webhook bot.
- `user`: send through your own Feishu/Lark account. The first run opens the OAuth authorization page and then stores `user_refresh_token` in `lark_config.json`.
- `app`: send through the app bot using `tenant_access_token`.

For Feishu China, use:

```json
{
  "open_platform_domain": "open.feishu.cn",
  "redirect_uri": "http://localhost:8765/callback",
  "user_scope": "im:message im:message.send_as_user im:message:recall"
}
```

#### 3. Run the full daily workflow

Use one of the explicit daily shortcuts:

```powershell
.\daily_webhook.bat
```

or:

```powershell
.\daily_as_me.bat
```

The workflow runs:

```text
1. update_report_data.py
2. build_message_pack.py
3. send_lark_images.py --send --send-as webhook/user
```

You can also call the Python entry directly:

```powershell
python run_daily_report.py --send-as webhook
python run_daily_report.py --send-as user
```

#### 4. Update only the workbook

```powershell
python update_report_data.py
```

Output:

```text
当日数据统计.xlsx
```

#### 5. Generate images only

```powershell
python build_message_pack.py
```

Images are generated under:

```text
output/supplier/
output/province/
```

This script now generates PNG images only. It no longer generates CSV or TXT files.

#### 6. Send images only

```powershell
python send_lark_images.py --send
```

The default is webhook-only. To send as your own account:

```powershell
.\send_as_me.bat
```

or:

```powershell
python send_lark_images.py --send --send-as user
```

If Lark rate-limits sending, increase the delay:

```powershell
python send_lark_images.py --send --delay 5
```

The script automatically retries when Lark returns rate limit code `11232`.

#### 7. Recall API-sent Messages

When `app` or `user` sending succeeds, the script stores the returned `message_id` in:

```text
output/sent_messages.jsonl
```

User tokens are cached in `output/lark_user_token.json` so repeated recalls do not open the authorization page for every message. `output/` is ignored by Git.

Recall the latest user-identity message:

```powershell
python send_lark_images.py --recall-last --send-as user
```

Recall the latest 3 user-identity messages:

```powershell
python send_lark_images.py --recall-last 3 --send-as user
```

Recall a specific `message_id`:

```powershell
python send_lark_images.py --recall-message om_xxxxxxxxx --send-as user
```

Webhook messages do not provide a reusable `message_id` here, so recall is supported for `app` / `user` API sends only.

#### 7. Generate tracking query text

```powershell
python getTrakingNum.py
```

Output:

```text
output/query_list.txt
```

### Outputs

#### Supplier images

Generated under:

```text
output/supplier/
```

Examples:

```text
Feng.png
SAFE.png
EMPIRE COURIER.png
```

#### Province / route images

Generated under:

```text
output/province/
```

Examples:

```text
非奥克兰总览.png
HMT各线路预测.png
TRG各线路预测.png
NPL_HST各线路预测.png
```

### Notes

- Open Excel workbooks may be locked and cannot be overwritten.
- Files inside `input/` and `output/` are ignored by Git.
- `lark_config.json` contains secrets and must not be committed.
- Sending many images to the same Lark chat can trigger rate limits. Use separate supplier groups or increase `--delay`.
- If Python writes formulas into Excel, Excel recalculates them when opened. The image generator also includes fallback route counting for key report areas.
