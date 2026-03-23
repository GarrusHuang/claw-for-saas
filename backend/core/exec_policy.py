"""
命令执行安全策略 — 三层防御架构。

层次:
1. 复合命令拆分 (管道/链/子命令)
2. 逐命令规则检查 (CommandRule: 子命令/标志白名单+黑名单)
3. 全局危险模式正则兜底

Usage:
    policy = ExecPolicy()
    safe, reason = policy.check_command("rm -rf /")
    # safe=False, reason="安全检查: 命令包含危险操作 — rm -rf /"
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandRule:
    """单条命令的安全规则。"""
    allowed_subcommands: frozenset[str] | None = None   # None = 全放行
    blocked_flags: frozenset[str] | None = None
    blocked_subcommands: frozenset[str] | None = None


# ── 命令规则表 ──

_COMMAND_RULES: dict[str, CommandRule] = {
    # Git: 只允许只读子命令
    "git": CommandRule(
        allowed_subcommands=frozenset({
            "status", "log", "diff", "branch", "show", "stash",
            "tag", "remote", "rev-parse", "ls-files", "blame",
            "shortlog", "describe", "config", "fetch",
            # 写入但常用且低风险
            "add", "commit", "checkout", "switch", "merge",
            "rebase", "pull", "push", "clone", "init",
        }),
        blocked_subcommands=frozenset({
            "reset --hard", "clean -f", "clean -fd", "clean -fx",
            "push --force", "push -f",
        }),
    ),
    # Python: 禁 -c 内联执行
    "python": CommandRule(blocked_flags=frozenset({"-c"})),
    "python3": CommandRule(blocked_flags=frozenset({"-c"})),
    # find: 禁执行/删除类标志
    "find": CommandRule(blocked_flags=frozenset({"-exec", "-execdir", "-delete", "-ok"})),
    # sed: 禁 in-place 修改
    "sed": CommandRule(blocked_flags=frozenset({"-i", "--in-place"})),
    # npm: 禁发布
    "npm": CommandRule(blocked_subcommands=frozenset({"publish", "unpublish", "adduser", "login"})),
    # 纯只读命令 — 全放行
    **{cmd: CommandRule() for cmd in [
        "ls", "cat", "head", "tail", "grep", "rg", "wc", "sort", "uniq",
        "cut", "pwd", "whoami", "date", "env", "which", "file", "stat",
        "du", "df", "tree", "diff", "less", "tr", "awk", "type",
    ]},
    # 低风险写入 — 全放行
    **{cmd: CommandRule() for cmd in [
        "mkdir", "touch", "cp", "mv", "echo", "cd",
    ]},
    # 开发工具 — 全放行
    **{cmd: CommandRule() for cmd in [
        "node", "npx", "yarn", "pip", "pip3",
    ]},
}

# ── 管道末端危险目标 ──

_PIPE_DANGEROUS_TARGETS = frozenset({
    "sh", "bash", "zsh", "dash", "csh", "ksh",
    "eval", "source", "exec",
    "python", "python3", "node", "perl", "ruby",
})

# ── 全局危险正则 (兜底) ──

_GLOBAL_DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"\bsudo\b",
    r"\bcurl\b.*\|\s*sh",
    r"\bwget\b.*\|\s*sh",
    r"\bmkfs\b",
    r":\(\)\s*\{",        # fork bomb
    r"\bdd\s+if=",
    r"\bchmod\s+777\s+/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+0\b",
    r"\bkill\s+-9\s+-1\b",
    r"\bpkill\s+-9\b",
    r"\bchown\s+root\b",
    r"\biptables\b",
    r"\bnc\s+-l\b",
]


def _split_compound(cmd: str) -> list[str]:
    """
    拆分复合命令: 管道 |、链式 &&/||/;、子命令 $()。

    引号感知: 引号内的分隔符不拆分。
    返回各子命令的 stripped 文本列表。
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    in_single = False
    in_double = False

    while i < len(cmd):
        c = cmd[i]

        # 引号状态切换
        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
            i += 1
            continue
        if c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
            i += 1
            continue

        if in_single or in_double:
            current.append(c)
            i += 1
            continue

        # $() 子命令提取
        if c == "$" and i + 1 < len(cmd) and cmd[i + 1] == "(":
            # 找到匹配的 )
            depth = 0
            j = i + 1
            while j < len(cmd):
                if cmd[j] == "(":
                    depth += 1
                elif cmd[j] == ")":
                    depth -= 1
                    if depth == 0:
                        # 提取子命令内容
                        inner = cmd[i + 2:j]
                        if inner.strip():
                            parts.extend(_split_compound(inner))
                        i = j + 1
                        break
                j += 1
            else:
                # 未闭合，当普通字符
                current.append(c)
                i += 1
            continue

        # 反引号 `` 子命令
        if c == "`":
            j = cmd.find("`", i + 1)
            if j > i:
                inner = cmd[i + 1:j]
                if inner.strip():
                    parts.extend(_split_compound(inner))
                i = j + 1
                continue

        # 分隔符: |, &&, ||, ;
        if c == "|":
            if i + 1 < len(cmd) and cmd[i + 1] == "|":
                # ||
                text = "".join(current).strip()
                if text:
                    parts.append(text)
                current = []
                i += 2
                continue
            else:
                # |
                text = "".join(current).strip()
                if text:
                    parts.append(text)
                current = []
                i += 1
                continue

        if c == "&" and i + 1 < len(cmd) and cmd[i + 1] == "&":
            text = "".join(current).strip()
            if text:
                parts.append(text)
            current = []
            i += 2
            continue

        if c == ";":
            text = "".join(current).strip()
            if text:
                parts.append(text)
            current = []
            i += 1
            continue

        current.append(c)
        i += 1

    # 最后一段
    text = "".join(current).strip()
    if text:
        parts.append(text)

    return parts


def _check_pipe_targets(sub_commands: list[str]) -> tuple[bool, str]:
    """
    管道末端检查: 末端是 shell/eval 等 → 阻止。

    只检查原始命令中管道分割的最后一段。
    返回 (safe, reason)。
    """
    if len(sub_commands) < 2:
        return True, ""

    last = sub_commands[-1]
    tokens = last.split()
    if not tokens:
        return True, ""
    first_token = tokens[0]

    if first_token in _PIPE_DANGEROUS_TARGETS:
        return False, f"安全检查: 管道输出到危险目标 {first_token} — {' | '.join(sub_commands)[:100]}"

    return True, ""


def _check_single_command(
    cmd: str,
    rules: dict[str, CommandRule],
    dangerous_re: list[re.Pattern],
) -> tuple[bool, str]:
    """检查单条命令的安全性。"""
    tokens = cmd.split()
    if not tokens:
        return True, ""

    first_token = tokens[0]

    # 查规则表
    rule = rules.get(first_token)

    if rule is not None:
        # 有规则 → 走子命令/标志分析

        # 1. 检查 blocked_subcommands (多 token 匹配)
        if rule.blocked_subcommands:
            for blocked in rule.blocked_subcommands:
                blocked_tokens = blocked.split()
                # 在 tokens[1:] 中查找连续匹配
                for i in range(1, len(tokens) - len(blocked_tokens) + 1):
                    if tokens[i:i + len(blocked_tokens)] == blocked_tokens:
                        return False, f"安全检查: {first_token} 的 {blocked} 操作被禁止 — {cmd[:100]}"

        # 2. 检查 blocked_flags
        if rule.blocked_flags:
            for token in tokens[1:]:
                # 精确匹配标志
                if token in rule.blocked_flags:
                    return False, f"安全检查: {first_token} 的 {token} 标志被禁止 — {cmd[:100]}"
                # 短标志组合: -ic → 检查 -i 和 -c
                if token.startswith("-") and not token.startswith("--") and len(token) > 2:
                    for flag in rule.blocked_flags:
                        if flag.startswith("-") and not flag.startswith("--") and len(flag) == 2:
                            if flag[1] in token[1:]:
                                return False, f"安全检查: {first_token} 的 {flag} 标志被禁止 — {cmd[:100]}"

        # 3. 检查 allowed_subcommands (如果定义了白名单)
        if rule.allowed_subcommands is not None and len(tokens) > 1:
            subcommand = tokens[1]
            if subcommand not in rule.allowed_subcommands:
                return False, f"安全检查: {first_token} {subcommand} 不在允许列表中 — {cmd[:100]}"

        return True, ""

    # 无规则 → 走全局黑名单
    for pattern in dangerous_re:
        if pattern.search(cmd):
            return False, f"安全检查: 命令包含危险操作 — {cmd[:100]}"

    return True, ""


class ExecPolicy:
    """命令执行安全策略 — 三层防御。"""

    # 敏感文件名 (禁止写入)
    SENSITIVE_FILES = [
        ".env", ".env.local", ".env.production",
        "credentials", "credentials.json",
        "id_rsa", "id_ed25519", "id_ecdsa",
        ".pem", ".key", ".p12", ".pfx",
        "shadow", "passwd",
    ]

    def __init__(
        self,
        extra_dangerous: list[str] | None = None,
        extra_safe: list[str] | None = None,
        approvals_dir: str = "data/exec_approvals",
    ) -> None:
        patterns = list(_GLOBAL_DANGEROUS_PATTERNS)
        if extra_dangerous:
            patterns.extend(extra_dangerous)
        self._dangerous_re = [re.compile(p, re.IGNORECASE) for p in patterns]

        # 构建命令规则表 (含额外安全命令)
        self._rules = dict(_COMMAND_RULES)
        if extra_safe:
            for prefix in extra_safe:
                if prefix not in self._rules:
                    self._rules[prefix] = CommandRule()

        # 5.6#16: per-user 命令审批持久化
        self._approvals_dir = approvals_dir

    def check_command(self, command: str) -> tuple[bool, str]:
        """
        检查命令安全性 — 三层防御。

        1. 拆分复合命令
        2. 管道末端检查
        3. 逐命令: 规则表 → 全局黑名单

        Returns:
            (is_safe, reason) — is_safe=True 允许执行, False 拒绝并返回原因
        """
        cmd = command.strip()
        if not cmd:
            return True, ""

        # 层 1: 拆分复合命令
        sub_commands = _split_compound(cmd)
        if not sub_commands:
            return True, ""

        # 层 2: 管道末端检查
        safe, reason = _check_pipe_targets(sub_commands)
        if not safe:
            return False, reason

        # 层 3: 逐命令检查
        for sub_cmd in sub_commands:
            safe, reason = _check_single_command(sub_cmd, self._rules, self._dangerous_re)
            if not safe:
                return False, reason

        return True, ""

    # ── 5.6#16: per-user 命令审批持久化 ──

    def _approvals_path(self, tenant_id: str, user_id: str) -> str:
        return os.path.join(self._approvals_dir, tenant_id, f"{user_id}.json")

    def load_approvals(self, tenant_id: str, user_id: str) -> list[str]:
        """加载用户已审批的命令模式列表。"""
        path = self._approvals_path(tenant_id, user_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return [e["pattern"] for e in data.get("approved_commands", [])]
        except (json.JSONDecodeError, OSError, KeyError):
            return []

    def approve_command(self, tenant_id: str, user_id: str, pattern: str) -> None:
        """持久化一条用户审批的命令模式。"""
        path = self._approvals_path(tenant_id, user_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data: dict = {"approved_commands": []}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        entries = data.setdefault("approved_commands", [])
        if not any(e["pattern"] == pattern for e in entries):
            entries.append({
                "pattern": pattern,
                "approved_at": datetime.now(timezone.utc).isoformat(),
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def is_approved(self, tenant_id: str, user_id: str, command: str) -> bool:
        """检查命令是否已被用户审批。"""
        for pattern in self.load_approvals(tenant_id, user_id):
            if command.strip().startswith(pattern):
                return True
        return False

    def check_command_with_approval(
        self, command: str, tenant_id: str = "", user_id: str = "",
    ) -> tuple[bool, str]:
        """check_command 增强版: 先查审批缓存，再走三层防御。"""
        if tenant_id and user_id and self.is_approved(tenant_id, user_id, command):
            return True, ""
        return self.check_command(command)

    def is_sensitive_file(self, path: str) -> bool:
        """检查文件名是否为敏感文件。"""
        basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        for sensitive in self.SENSITIVE_FILES:
            if basename == sensitive or basename.endswith(sensitive):
                return True
        return False
