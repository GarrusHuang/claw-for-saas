/**
 * 工具中文标签映射 — 将英文工具名翻译为用户友好的中文描述。
 */

const TOOL_LABELS: Record<string, string> = {
  // Calculator
  numeric_compare: '数值比较',
  sum_values: '求和计算',
  calculate_ratio: '比率计算',
  arithmetic: '算术运算',
  date_diff: '日期差计算',

  // Skill
  read_reference: '读取参考资料',
  read_skill: '读取技能',

  // File
  read_uploaded_file: '读取文件',
  list_user_files: '列出文件',
  analyze_file: '分析文件',
  process_file_content: '处理文件内容',
  read_knowledge_file: '读取知识库',
  add_to_knowledge_base: '添加到知识库',

  // Browser
  open_url: '打开网页',
  page_screenshot: '页面截图',
  page_extract_text: '提取网页文本',

  // Code
  read_source_file: '读取文件',
  write_source_file: '写入文件',
  run_command: '执行命令',

  // Memory
  save_memory: '保存记忆',
  recall_memory: '回忆记忆',

  // Skill Management
  create_skill: '创建技能',
  update_skill: '更新技能',

  // Schedule
  create_schedule: '创建定时任务',
  list_schedules: '列出定时任务',
  delete_schedule: '删除定时任务',

  // Plan
  propose_plan: '制定计划',
  propose_plan_with_review: '制定审查计划',
  update_plan_step: '更新进度',

  // Subagent
  spawn_subagent: '启动子智能体',
  spawn_subagents: '批量启动子智能体',

  // MCP
  get_form_schema: '获取表单结构',
  get_business_rules: '获取业务规则',
  get_candidate_types: '获取候选类型',
  get_protected_values: '获取保护值',
  submit_form_data: '提交表单',
  query_data: '查询数据',
};

/** 获取工具的中文标签，未映射时返回原名 */
export function getToolLabel(toolName: string): string {
  return TOOL_LABELS[toolName] || toolName;
}

/** 从文件路径推断编程语言 (用于语法高亮) */
export function getLanguageFromExt(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || '';
  const map: Record<string, string> = {
    py: 'python', js: 'javascript', ts: 'typescript',
    tsx: 'tsx', jsx: 'jsx', svg: 'xml', xml: 'xml',
    html: 'html', css: 'css', json: 'json',
    sh: 'bash', bash: 'bash', sql: 'sql',
    md: 'markdown', yaml: 'yaml', yml: 'yaml',
    go: 'go', java: 'java', rs: 'rust', c: 'c',
  };
  return map[ext] || 'text';
}
