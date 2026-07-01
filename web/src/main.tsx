import React, { ChangeEvent, DragEvent, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Check, Clipboard, FileSpreadsheet, Upload, X } from "lucide-react";
import * as XLSX from "xlsx";
import "./styles.css";

const TRACKING_COLUMN_KEYWORDS = ["trackingno", "billnumber", "imile单号"];

type FileResult = {
  fileName: string;
  matchedColumns: string[];
  records: number;
  error?: string;
};

function normalizeColumnName(column: unknown) {
  return String(column).trim().toLowerCase();
}

function findColumn(columns: string[], keyword: string) {
  const normalizedKeyword = keyword.toLowerCase();
  return columns.find((column) => normalizeColumnName(column).includes(normalizedKeyword));
}

function cleanValue(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

async function extractTrackingNumbers(files: File[]) {
  const allNumbers: string[] = [];
  const fileResults: FileResult[] = [];

  for (const file of files) {
    if (file.name.startsWith("~$")) {
      continue;
    }

    try {
      const buffer = await file.arrayBuffer();
      const workbook = XLSX.read(buffer, { type: "array", cellDates: false });
      const firstSheetName = workbook.SheetNames[0];

      if (!firstSheetName) {
        fileResults.push({
          fileName: file.name,
          matchedColumns: [],
          records: 0,
          error: "文件里没有工作表",
        });
        continue;
      }

      const sheet = workbook.Sheets[firstSheetName];
      const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, {
        defval: "",
        raw: false,
      });
      const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
      const matchedColumns = Array.from(
        new Set(
          TRACKING_COLUMN_KEYWORDS.map((keyword) => findColumn(columns, keyword)).filter(
            (column): column is string => Boolean(column),
          ),
        ),
      );

      if (matchedColumns.length === 0) {
        fileResults.push({
          fileName: file.name,
          matchedColumns: [],
          records: 0,
          error: "没有找到 TrackingNo、BillNumber 或 IMILE单号 列",
        });
        continue;
      }

      let records = 0;
      for (const row of rows) {
        for (const column of matchedColumns) {
          const value = cleanValue(row[column]);
          if (value) {
            allNumbers.push(value);
            records += 1;
          }
        }
      }

      fileResults.push({
        fileName: file.name,
        matchedColumns,
        records,
      });
    } catch (error) {
      fileResults.push({
        fileName: file.name,
        matchedColumns: [],
        records: 0,
        error: error instanceof Error ? error.message : "读取失败",
      });
    }
  }

  return {
    numbers: Array.from(new Set(allNumbers)).sort(),
    fileResults,
  };
}

function App() {
  const [files, setFiles] = useState<File[]>([]);
  const [numbers, setNumbers] = useState<string[]>([]);
  const [fileResults, setFileResults] = useState<FileResult[]>([]);
  const [status, setStatus] = useState("请选择 Excel 文件");
  const [isBusy, setIsBusy] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const copiedText = useMemo(() => numbers.join("\r\n"), [numbers]);

  function addFiles(nextFiles: FileList | File[]) {
    const excelFiles = Array.from(nextFiles).filter((file) => /\.(xls|xlsx)$/i.test(file.name));
    setFiles(excelFiles);
    setNumbers([]);
    setFileResults([]);
    setStatus(excelFiles.length ? `已选择 ${excelFiles.length} 个 Excel 文件` : "请选择 .xls 或 .xlsx 文件");
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) {
      addFiles(event.target.files);
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    addFiles(event.dataTransfer.files);
  }

  async function copyText(text: string) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.setAttribute("readonly", "");
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand("copy");
    document.body.removeChild(textArea);
  }

  async function handleGetTrackingNum() {
    if (!files.length) {
      setStatus("请先上传 Excel 文件");
      inputRef.current?.click();
      return;
    }

    setIsBusy(true);
    setStatus("正在读取文件...");

    const result = await extractTrackingNumbers(files);
    setNumbers(result.numbers);
    setFileResults(result.fileResults);

    if (!result.numbers.length) {
      setStatus("没有提取到可复制的单号");
      setIsBusy(false);
      return;
    }

    try {
      await copyText(result.numbers.join("\r\n"));
      setStatus(`已复制 ${result.numbers.length} 个唯一单号`);
    } catch {
      setStatus("已提取单号，但浏览器阻止了自动复制，可手动复制下方文本");
    } finally {
      setIsBusy(false);
    }
  }

  function clearFiles() {
    setFiles([]);
    setNumbers([]);
    setFileResults([]);
    setStatus("请选择 Excel 文件");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }

  return (
    <main className="app-shell">
      <section className="workspace">
        <div className="topbar">
          <div>
            <p className="eyebrow">iMile Tool</p>
            <h1>Get Tracking Num</h1>
          </div>
          <span className={numbers.length ? "status status-ready" : "status"}>{status}</span>
        </div>

        <div
          className={isDragging ? "upload-zone upload-zone-active" : "upload-zone"}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
        >
          <input
            ref={inputRef}
            className="file-input"
            type="file"
            accept=".xls,.xlsx"
            multiple
            onChange={handleFileChange}
          />
          <button className="upload-button" type="button" onClick={() => inputRef.current?.click()}>
            <Upload size={18} />
            上传 Excel
          </button>
          <div className="upload-copy">
            <strong>{files.length ? `${files.length} 个文件已就绪` : "拖入或选择订单明细"}</strong>
            <span>支持 .xls / .xlsx，会读取第一个工作表。</span>
          </div>
          {files.length > 0 && (
            <button className="icon-button" type="button" aria-label="清空文件" onClick={clearFiles}>
              <X size={18} />
            </button>
          )}
        </div>

        {files.length > 0 && (
          <div className="file-list" aria-label="已选择文件">
            {files.map((file) => (
              <div className="file-row" key={`${file.name}-${file.size}`}>
                <FileSpreadsheet size={17} />
                <span>{file.name}</span>
              </div>
            ))}
          </div>
        )}

        <div className="action-row">
          <button className="primary-action" type="button" disabled={isBusy} onClick={handleGetTrackingNum}>
            {isBusy ? <Clipboard size={18} /> : <Check size={18} />}
            {isBusy ? "处理中..." : "getTrakingNum"}
          </button>
          <span>{numbers.length ? `预览 ${numbers.length} 个唯一单号` : "点击后自动复制到剪贴板"}</span>
        </div>

        {fileResults.length > 0 && (
          <section className="result-panel" aria-label="处理结果">
            <div className="result-header">
              <h2>处理结果</h2>
              <button className="copy-again" type="button" disabled={!copiedText} onClick={() => copyText(copiedText)}>
                <Clipboard size={16} />
                再复制一次
              </button>
            </div>
            <div className="result-grid">
              {fileResults.map((result) => (
                <div className={result.error ? "result-item result-error" : "result-item"} key={result.fileName}>
                  <strong>{result.fileName}</strong>
                  <span>
                    {result.error
                      ? result.error
                      : `${result.records} 条，列：${result.matchedColumns.join(" / ")}`}
                  </span>
                </div>
              ))}
            </div>
            <textarea className="numbers-preview" value={copiedText} readOnly spellCheck={false} />
          </section>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
