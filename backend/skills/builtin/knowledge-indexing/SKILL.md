---
name: knowledge-indexing
type: capability
version: "1.1"
description: "知识库索引自动维护 — 文件入库后自动生成摘要并更新 _index.md"
applies_to: [universal]
---

# 知识库索引维护

## 重要规则

1. **必须使用 `add_to_knowledge_base` 工具** — 不要用 `write_source_file` 直接写知识库目录，否则文件不会出现在知识库列表中。
2. **scope 始终为 user** — 普通用户只能添加到个人知识库，不可写入 global 共享知识库。`add_to_knowledge_base` 工具已强制 user scope。
3. **通过界面上传的文件** — 系统会自动生成索引，你不需要额外处理。

## 触发条件

以下场景你**必须**自动执行，不需要用户额外指示：

1. **用户在对话中要求将内容加入知识库** — 如"把这个文件存到知识库"、"加入知识库"、"收藏到知识库"等
2. **知识库文件被删除** — 从索引中移除对应条目

## 工作流程

### 场景 1: 用户要求将上传文件加入知识库

1. 使用 `add_to_knowledge_base(filename="xxx", source_file_id="xxx", description="xxx")` 将文件添加到知识库
2. 工具会自动创建元数据、触发索引更新
3. 告知用户文件已添加

### 场景 2: 用户要求将文本内容加入知识库

1. 使用 `add_to_knowledge_base(filename="xxx.md", text_content="...", description="xxx")` 将内容添加到知识库
2. 工具会自动创建元数据、触发索引更新
3. 告知用户内容已添加

### 场景 3: 文件删除

1. 读取 `_index.md`
2. 移除被删除文件对应的 `## {file_id}: ...` 段落
3. 写回 `_index.md`

## 注意事项

- **不要** 使用 `write_source_file` 向 `data/knowledge/` 目录写入文件
- **不要** 将文件添加到 global scope — 那是管理员通过后台管理的
- 摘要的目的是帮助未来对话判断是否需要 `read_knowledge_file` 读取全文
