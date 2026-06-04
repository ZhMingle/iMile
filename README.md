# iMile Daily Report Automation

## 中文说明

### 项目目的

这个项目用于自动化 iMile 每日到件统计和飞书分发流程。实际业务里，最原始的数据来自订单明细，例如 Temu/清关公司文件、菜鸟邮件附件等；这些订单明细会先被整理成查询单号，再到内部系统查询得到“中心运单查询”数据。最后，脚本会把中心运单查询结果写入 `当日数据统计.xlsx`，生成最终想要的统计结果和飞书图片。

以前这些步骤需要手动复制单号、粘贴到内部系统查询、再把统计结果和截图复制粘贴到不同飞书群。这个项目把后半段重复操作自动化：

- 从 `input/` 的原始订单明细中提取查询单号
- 用内部系统导出的“中心运单查询”文件更新 `当日数据统计.xlsx`
- 生成供应商分单、非奥克兰总览和线路预测图片
- 按飞书配置把图片发送到对应群

项目适合每天重复使用，减少人工统计、截图和逐群复制粘贴图片的工作量。

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

中心运单查询文件不是最原始数据，而是通过 `output/query_list.txt` 里的单号，在内部系统查询后导出的结果文件。

文件名需要匹配：

```text
*中心运单查询*.xlsx
```

脚本会自动选择最新且列名完整的文件。必须包含以下列：

```text
运单号
路由码
派件网点简码
```

常见派件网点简码包括：

```text
AKL, HMT, TRG, WLT, NPL, PMN, RTR, WGR, HST
```

其中：

- `AKL` 用于奥克兰分单统计
- 非 `AKL` 用于非奥克兰到件货量统计
- 运单号以 `36` 开头的记录会被用于 AliExpress / 菜鸟相关统计

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

然后把 `output/query_list.txt` 里的单号复制到内部系统查询，并导出中心运单查询文件。将最新的中心运单查询文件放在项目根目录，例如：

```text
中心运单查询 (3).xlsx
```

#### 2. 配置飞书

复制配置模板：

```powershell
copy lark_config.example.json lark_config.json
```

然后在 `lark_config.json` 中填写真实的：

```text
app_id
app_secret
webhook 或 receive_id_type + receive_id
```

`lark_config.json` 已被 `.gitignore` 忽略，不会提交到 Git。

#### 3. 一键运行日报流程

```powershell
python run_daily_report
```

或者：

```powershell
python run_daily_report.py
```

Windows 下也可以运行：

```powershell
.\run_daily_report.bat
```

执行顺序是：

```text
1. update_report_data.py
2. build_message_pack.py
3. send_lark_images.py --send
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

如果遇到飞书限流，可以增加发送间隔：

```powershell
python send_lark_images.py --send --delay 5
```

脚本遇到飞书限流 `11232` 时会自动等待并重试。

#### 7. 生成查询单号文本

```powershell
python getTrakingNum.py
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
- Update `当日数据统计.xlsx` using the internal-system center waybill query export
- Generate supplier dispatch, non-Auckland overview, and route forecast images
- Send images to configured Lark groups

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
```

Common station codes:

```text
AKL, HMT, TRG, WLT, NPL, PMN, RTR, WGR, HST
```

Rules:

- `AKL` is used for Auckland dispatch statistics
- Non-`AKL` rows are used for non-Auckland inbound statistics
- Waybill numbers starting with `36` are counted for AliExpress / Cainiao-related metrics

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
webhook or receive_id_type + receive_id
```

`lark_config.json` is ignored by Git.

#### 3. Run the full daily workflow

```powershell
python run_daily_report
```

or:

```powershell
python run_daily_report.py
```

On Windows, you can also run:

```powershell
.\run_daily_report.bat
```

The workflow runs:

```text
1. update_report_data.py
2. build_message_pack.py
3. send_lark_images.py --send
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

If Lark rate-limits sending, increase the delay:

```powershell
python send_lark_images.py --send --delay 5
```

The script automatically retries when Lark returns rate limit code `11232`.

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
