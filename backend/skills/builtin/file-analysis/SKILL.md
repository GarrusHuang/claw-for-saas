---
name: file-analysis
type: capability
version: "1.0"
description: "文件分析与文本提取能力"
applies_to: [universal]
---

# 文件分析能力

## 支持格式

| 格式 | 提取方式 | 关键信息 |
|------|----------|----------|
| PDF | PyPDF2 逐页提取 | 页数、每页文本 |
| DOCX | python-docx 段落提取 | 段落数、表格数 |
| TXT/CSV/JSON/XML/YAML/MD | 直接读取 | 行数、字符数 |
| 图片 (PNG/JPG/GIF/WebP) | Pillow 元信息 | 尺寸、格式、模式 |

## 工作流程

1. **发现文件**: `list_user_files()` → 获取文件列表 (file_id, filename, size)
2. **读取内容**: `read_uploaded_file(file_id)` → 获取提取的文本
3. **结构分析**: `analyze_file(file_id)` → 获取详细元信息 (页数/行数/尺寸)

## 常见场景

### 报销材料分析
- 用户上传发票 PDF → 提取发票号码/金额/日期
- 用户上传行程单 → 提取出差信息

### 合同文档分析
- 用户上传合同草稿 DOCX → 提取条款内容
- 用户上传供应商资质 PDF → 提取资质信息

### 数据文件分析
- 用户上传 CSV 数据 → 提取列名/行数/样本数据
- 用户上传 JSON 配置 → 解析结构

## 注意事项

- 图片文件仅返回元信息 (尺寸/格式)，不做 OCR
- 大文件文本可能被截断 (受 max_tool_result_chars 限制)
- 文件大小限制: 10MB
