import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = path.resolve("outputs", "019ffe1d-3254-71f3-9264-053ca383d209");
const outputPath = path.join(outputDir, "CSP借用物资统计.xlsx");
const previewPath = path.join(outputDir, "CSP借用物资统计-preview.png");

await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("借用物资统计");
sheet.showGridLines = false;

sheet.getRange("A1:F1").merge();
sheet.getRange("A1").values = [["CSP借用物资统计"]];
sheet.getRange("A1:F1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF", size: 18 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange("A1:F1").format.rowHeight = 34;

sheet.getRange("A2:F2").merge();
sheet.getRange("A2").values = [["各站点借用设备及笼车数量汇总"]];
sheet.getRange("A2:F2").format = {
  fill: "#D9EAF7",
  font: { color: "#1F4E78", size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange("A2:F2").format.rowHeight = 22;

sheet.getRange("A4:F9").values = [
  ["站点/区域", "安卓手机", "PDA", "面单打印机", "扫描枪", "笼车"],
  ["Hamilton", 1, 0, 2, 1, 6],
  ["TRG、RTR、TPO、PMN（共用）", 0, 1, 1, 1, 0],
  ["NPL & HST（共用）", 0, 1, 1, 1, 0],
  ["WLT", 0, 1, 1, 1, 0],
  ["总计", null, null, null, null, null],
];

sheet.getRange("B9:F9").formulas = [[
  "=SUM(B5:B8)",
  "=SUM(C5:C8)",
  "=SUM(D5:D8)",
  "=SUM(E5:E8)",
  "=SUM(F5:F8)",
]];

sheet.getRange("A4:F4").format = {
  fill: "#5B9BD5",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#8EA9C1" },
};
sheet.getRange("A4:F4").format.rowHeight = 28;

sheet.getRange("A5:F8").format = {
  fill: "#FFFFFF",
  font: { color: "#1F2937", size: 10 },
  verticalAlignment: "center",
  borders: {
    insideHorizontal: { style: "thin", color: "#D9E2F3" },
    bottom: { style: "thin", color: "#A6B7C8" },
    left: { style: "thin", color: "#A6B7C8" },
    right: { style: "thin", color: "#A6B7C8" },
  },
};
sheet.getRange("A5:A8").format.horizontalAlignment = "left";
sheet.getRange("B5:F9").format.horizontalAlignment = "center";
sheet.getRange("B5:F9").format.numberFormat = "#,##0";
sheet.getRange("A5:F8").format.rowHeight = 24;

sheet.getRange("A9:F9").format = {
  fill: "#E2F0D9",
  font: { bold: true, color: "#375623" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: {
    top: { style: "double", color: "#70AD47" },
    bottom: { style: "thin", color: "#70AD47" },
    left: { style: "thin", color: "#70AD47" },
    right: { style: "thin", color: "#70AD47" },
  },
};
sheet.getRange("A9:F9").format.rowHeight = 26;

sheet.getRange("A11:F11").merge();
sheet.getRange("A11").values = [["说明：TRG、RTR、TPO、PMN 四个站点共用一套设备；NPL 与 HST 共用一套设备。"]];
sheet.getRange("A11:F11").format = {
  fill: "#FFF2CC",
  font: { italic: true, color: "#7F6000", size: 9 },
  horizontalAlignment: "left",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#E6B800" },
};
sheet.getRange("A11:F11").format.rowHeight = 28;

sheet.getRange("A1:A11").format.font = { name: "Microsoft YaHei" };
sheet.getRange("B1:F11").format.font = { name: "Microsoft YaHei" };
sheet.getRange("A:A").format.columnWidth = 32;
sheet.getRange("B:B").format.columnWidth = 12;
sheet.getRange("C:C").format.columnWidth = 10;
sheet.getRange("D:D").format.columnWidth = 14;
sheet.getRange("E:E").format.columnWidth = 11;
sheet.getRange("F:F").format.columnWidth = 10;
sheet.freezePanes.freezeRows(4);

const check = await workbook.inspect({
  kind: "table",
  range: "借用物资统计!A1:F11",
  include: "values,formulas",
  tableMaxRows: 15,
  tableMaxCols: 8,
  maxChars: 5000,
});
console.log("TABLE_CHECK");
console.log(check.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
  maxChars: 3000,
});
console.log("ERROR_SCAN");
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "借用物资统计",
  range: "A1:F11",
  scale: 2,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
console.log(`PREVIEW=${previewPath}`);
