"""
知识库服务 — 全局/用户知识文件管理。

存储结构:
    data/knowledge/
    ├── global/                     # 共享知识 (管理员上传)
    │   ├── {file_id}.{ext}
    │   └── {file_id}.meta.json
    └── {tenant_id}/{user_id}/      # 用户知识
        ├── {file_id}.{ext}
        └── {file_id}.meta.json
"""
from __future__ import annotations
import hashlib, json, logging, mimetypes, os, re, time, uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class KBFileMeta:
    file_id: str
    filename: str
    content_type: str
    size_bytes: int
    owner_id: str        # user who uploaded
    tenant_id: str
    scope: str           # "global" or "user"
    created_at: float
    description: str = ""
    sha256: str = ""

class KnowledgeService:
    def __init__(self, base_dir: str = "data/knowledge") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # #49: 元数据内存缓存 (file_id → KBFileMeta)
        self._meta_cache: dict[str, KBFileMeta] = {}
        self._cache_built = False

    def _scope_dir(self, tenant_id: str, user_id: str, scope: str) -> Path:
        if scope == "global":
            d = self.base_dir / "global"
        else:
            safe_tid = re.sub(r'[^\w\-]', '_', tenant_id)
            safe_uid = re.sub(r'[^\w\-]', '_', user_id)
            d = self.base_dir / safe_tid / safe_uid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_file(self, tenant_id: str, user_id: str, filename: str, content: bytes, scope: str = "user", description: str = "", is_admin: bool = False) -> KBFileMeta:
        """Add a file to knowledge base. Only admins can write to global scope."""
        if scope == "global" and not is_admin:
            raise PermissionError("只有管理员可以添加全局知识库文件")
        safe_name = os.path.basename(filename)
        safe_name = re.sub(r'[^\w.\-]', '_', safe_name) or "unnamed"
        ext = Path(safe_name).suffix.lower()

        file_id = str(uuid.uuid4())[:12]
        sha256 = hashlib.sha256(content).hexdigest()
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

        scope_dir = self._scope_dir(tenant_id, user_id, scope)
        file_path = scope_dir / f"{file_id}{ext}"
        file_path.write_bytes(content)

        meta = KBFileMeta(
            file_id=file_id, filename=safe_name, content_type=content_type,
            size_bytes=len(content), owner_id=user_id, tenant_id=tenant_id,
            scope=scope, created_at=time.time(), description=description, sha256=sha256,
        )
        meta_path = scope_dir / f"{file_id}.meta.json"
        meta_path.write_text(json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")

        # #49: 更新缓存 + 自动重建索引
        self._meta_cache[file_id] = meta
        try:
            self.update_index(tenant_id, user_id, scope)
        except Exception as e:
            logger.debug(f"Index update after add_file failed: {e}")

        logger.info("KB file added: %s (%s, scope=%s)", safe_name, file_id, scope)
        return meta

    def list_files(self, tenant_id: str, user_id: str) -> list[KBFileMeta]:
        """List global + user's knowledge files."""
        results = []
        # Global
        global_dir = self.base_dir / "global"
        if global_dir.exists():
            results.extend(self._scan_dir(global_dir))
        # User
        safe_tid = re.sub(r'[^\w\-]', '_', tenant_id)
        safe_uid = re.sub(r'[^\w\-]', '_', user_id)
        user_dir = self.base_dir / safe_tid / safe_uid
        if user_dir.exists():
            results.extend(self._scan_dir(user_dir))
        return sorted(results, key=lambda m: m.created_at, reverse=True)

    def _scan_dir(self, d: Path) -> list[KBFileMeta]:
        results = []
        for mf in d.glob("*.meta.json"):
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                results.append(KBFileMeta(**data))
            except Exception as e:
                logger.warning("Failed to load KB meta %s: %s", mf, e)
        return results

    def get_file(self, file_id: str) -> tuple[KBFileMeta, bytes] | None:
        """Find and return a KB file by id (searches all directories)."""
        for meta_path in self.base_dir.rglob(f"{file_id}.meta.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                meta = KBFileMeta(**data)
                ext = Path(meta.filename).suffix.lower()
                file_path = meta_path.parent / f"{file_id}{ext}"
                if file_path.exists():
                    return meta, file_path.read_bytes()
            except Exception:
                pass
        return None

    def get_file_meta(self, file_id: str) -> KBFileMeta | None:
        """Get metadata only."""
        for meta_path in self.base_dir.rglob(f"{file_id}.meta.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                return KBFileMeta(**data)
            except Exception:
                pass
        return None

    def delete_file(self, tenant_id: str, user_id: str, file_id: str) -> bool:
        """Delete a KB file. Only owner can delete."""
        meta = self.get_file_meta(file_id)
        if not meta:
            return False
        if meta.owner_id != user_id:
            raise PermissionError("只能删除自己上传的知识文件")

        # Find and delete
        for meta_path in self.base_dir.rglob(f"{file_id}.meta.json"):
            ext = Path(meta.filename).suffix.lower()
            file_path = meta_path.parent / f"{file_id}{ext}"
            if file_path.exists():
                file_path.unlink()
            meta_path.unlink()
            # #49: 清除缓存 + 重建索引
            self._meta_cache.pop(file_id, None)
            try:
                self.update_index(meta.tenant_id, meta.owner_id, meta.scope)
            except Exception as e:
                logger.debug(f"Index update after delete_file failed: {e}")
            logger.info("KB file deleted: %s", file_id)
            return True
        return False

    def get_index_paths(self, tenant_id: str, user_id: str) -> list[Path]:
        """返回应加载的 _index.md 路径列表（全局 + 用户级）。"""
        paths = []
        global_index = self.base_dir / "global" / "_index.md"
        paths.append(global_index)
        safe_tid = re.sub(r'[^\w\-]', '_', tenant_id)
        safe_uid = re.sub(r'[^\w\-]', '_', user_id)
        user_index = self.base_dir / safe_tid / safe_uid / "_index.md"
        paths.append(user_index)
        return paths

    # ── #49-51: 知识库智能索引 ──

    def _ensure_cache(self) -> None:
        """懒初始化: 首次访问时扫描全部 .meta.json 构建内存缓存。"""
        if self._cache_built:
            return
        for meta_path in self.base_dir.rglob("*.meta.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                meta = KBFileMeta(**data)
                self._meta_cache[meta.file_id] = meta
            except Exception:
                pass
        self._cache_built = True
        logger.info(f"KB meta cache built: {len(self._meta_cache)} files")

    def get_file_meta_cached(self, file_id: str) -> KBFileMeta | None:
        """从内存缓存获取元数据 (O(1) 查找)。"""
        self._ensure_cache()
        return self._meta_cache.get(file_id)

    def list_files_cached(self, tenant_id: str, user_id: str) -> list[KBFileMeta]:
        """从内存缓存列出文件 (不再 rglob)。"""
        self._ensure_cache()
        results = []
        for meta in self._meta_cache.values():
            if meta.scope == "global" or (meta.tenant_id == tenant_id and meta.owner_id == user_id):
                results.append(meta)
        return sorted(results, key=lambda m: m.created_at, reverse=True)

    def search_knowledge(self, tenant_id: str, user_id: str, query: str, limit: int = 10) -> list[dict]:
        """
        #51: search_knowledge — 搜索知识库。

        搜索范围: _index.md 全文 + 元数据缓存 (文件名 + 描述)。
        返回匹配的文件列表 (file_id + 文件名 + 匹配摘要)。
        """
        self._ensure_cache()
        query_lower = query.lower().strip()
        if not query_lower:
            return []

        results: list[tuple[float, dict]] = []

        for meta in self._meta_cache.values():
            # 权限过滤
            if meta.scope != "global" and (meta.tenant_id != tenant_id or meta.owner_id != user_id):
                continue

            # 搜索: 文件名 + 描述
            text = f"{meta.filename} {meta.description}".lower()
            score = 0.0
            for term in query_lower.split():
                if term in text:
                    score += 1.0
                if term in meta.filename.lower():
                    score += 0.5  # 文件名匹配加权

            if score > 0:
                snippet = meta.description[:100] if meta.description else meta.filename
                results.append((score, {
                    "file_id": meta.file_id,
                    "filename": meta.filename,
                    "description": meta.description,
                    "content_type": meta.content_type,
                    "size_bytes": meta.size_bytes,
                    "match_snippet": snippet,
                }))

        results.sort(key=lambda x: -x[0])
        return [r[1] for r in results[:limit]]

    def update_index(self, tenant_id: str, user_id: str, scope: str = "user") -> str:
        """
        #49: 自动生成/更新 _index.md。

        格式: 每个文件一行，含 file_id、文件名、描述、关键词。
        返回生成的 _index.md 内容。
        """
        self._ensure_cache()

        files = []
        for meta in self._meta_cache.values():
            if scope == "global" and meta.scope == "global":
                files.append(meta)
            elif scope == "user" and meta.tenant_id == tenant_id and meta.owner_id == user_id:
                files.append(meta)

        files.sort(key=lambda m: m.created_at, reverse=True)

        lines = ["# 知识库文件索引", ""]
        for meta in files:
            desc = meta.description or "无描述"
            size_kb = round(meta.size_bytes / 1024, 1)
            lines.append(
                f"- **{meta.filename}** (file_id: `{meta.file_id}`, {size_kb}KB) — {desc}"
            )
        lines.append("")
        lines.append("使用 `read_knowledge_file(file_id)` 读取文件内容。")
        lines.append("使用 `search_knowledge(query)` 按关键词搜索更多文件。")

        content = "\n".join(lines)

        # 写入 _index.md
        scope_dir = self._scope_dir(tenant_id, user_id, scope)
        index_path = scope_dir / "_index.md"
        index_path.write_text(content, encoding="utf-8")
        logger.info(f"KB index updated: {index_path} ({len(files)} files)")
        return content

    def extract_text(self, file_id: str) -> str:
        """Extract text content from a KB file."""
        result = self.get_file(file_id)
        if not result:
            return ""
        meta, content = result
        ext = Path(meta.filename).suffix.lower()
        try:
            if ext == ".pdf":
                import io
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(content))
                pages = [p.extract_text() or "" for p in reader.pages]
                return "\n\n".join(p for p in pages if p.strip())
            elif ext in (".docx", ".doc"):
                import io
                from docx import Document
                doc = Document(io.BytesIO(content))
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            elif ext in (".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".md", ".py", ".js", ".ts", ".html", ".css"):
                try:
                    return content.decode("utf-8")
                except UnicodeDecodeError:
                    return content.decode("utf-8", errors="replace")
            else:
                return f"[{meta.filename}] ({meta.content_type}, {meta.size_bytes} bytes)"
        except Exception as e:
            return f"[文本提取失败: {e}]"
