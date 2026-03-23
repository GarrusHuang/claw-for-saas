"""
#49-51: 知识库智能索引测试。

- _index.md 自动生成/更新
- 元数据内存缓存
- search_knowledge 搜索
- add_file/delete_file 自动更新索引
"""

import os
import pytest

from services.knowledge_service import KnowledgeService, KBFileMeta


@pytest.fixture
def kb(tmp_path):
    return KnowledgeService(base_dir=str(tmp_path))


class TestMetaCache:

    def test_ensure_cache_builds(self, kb):
        # 手动添加一个文件
        kb.add_file("T1", "U1", "test.txt", b"hello world", description="测试文件")
        # 清除缓存强制重建
        kb._meta_cache.clear()
        kb._cache_built = False
        kb._ensure_cache()
        assert len(kb._meta_cache) == 1

    def test_get_file_meta_cached(self, kb):
        meta = kb.add_file("T1", "U1", "data.csv", b"a,b,c", description="CSV 数据")
        result = kb.get_file_meta_cached(meta.file_id)
        assert result is not None
        assert result.filename == "data.csv"

    def test_list_files_cached(self, kb):
        kb.add_file("T1", "U1", "a.txt", b"a", scope="user")
        kb.add_file("T1", "U1", "b.txt", b"b", scope="user")
        files = kb.list_files_cached("T1", "U1")
        assert len(files) == 2

    def test_cache_isolation(self, kb):
        kb.add_file("T1", "U1", "u1.txt", b"u1")
        kb.add_file("T1", "U2", "u2.txt", b"u2")
        files = kb.list_files_cached("T1", "U1")
        names = [f.filename for f in files]
        assert "u1.txt" in names
        assert "u2.txt" not in names


class TestAutoIndex:

    def test_index_generated_on_add(self, kb):
        meta = kb.add_file("T1", "U1", "report.pdf", b"pdf content", description="月度报告")
        # _index.md 应已生成
        index_paths = kb.get_index_paths("T1", "U1")
        user_index = index_paths[1]  # user-level
        assert user_index.exists()
        content = user_index.read_text(encoding="utf-8")
        assert "report.pdf" in content
        assert meta.file_id in content
        assert "月度报告" in content

    def test_index_updated_on_delete(self, kb):
        meta1 = kb.add_file("T1", "U1", "keep.txt", b"keep", description="保留")
        meta2 = kb.add_file("T1", "U1", "remove.txt", b"remove", description="删除")
        kb.delete_file("T1", "U1", meta2.file_id)
        index_path = kb.get_index_paths("T1", "U1")[1]
        content = index_path.read_text(encoding="utf-8")
        assert "keep.txt" in content
        assert "remove.txt" not in content

    def test_update_index_manual(self, kb):
        kb.add_file("T1", "U1", "doc.md", b"# Title", description="文档")
        content = kb.update_index("T1", "U1", "user")
        assert "doc.md" in content
        assert "search_knowledge" in content

    def test_index_contains_hint(self, kb):
        kb.add_file("T1", "U1", "f.txt", b"x")
        content = kb.update_index("T1", "U1", "user")
        assert "read_knowledge_file" in content
        assert "search_knowledge" in content


class TestSearchKnowledge:

    def test_search_by_filename(self, kb):
        kb.add_file("T1", "U1", "财务报告.xlsx", b"data", description="2024年度财务")
        kb.add_file("T1", "U1", "会议纪要.docx", b"data", description="周会记录")
        results = kb.search_knowledge("T1", "U1", "财务")
        assert len(results) >= 1
        assert results[0]["filename"] == "财务报告.xlsx"

    def test_search_by_description(self, kb):
        kb.add_file("T1", "U1", "data.csv", b"x", description="员工薪资数据")
        results = kb.search_knowledge("T1", "U1", "薪资")
        assert len(results) == 1
        assert results[0]["file_id"]

    def test_search_no_match(self, kb):
        kb.add_file("T1", "U1", "test.txt", b"x")
        results = kb.search_knowledge("T1", "U1", "不存在的关键词xyz")
        assert results == []

    def test_search_respects_scope(self, kb):
        kb.add_file("T1", "U1", "u1.txt", b"x", description="用户1数据")
        kb.add_file("T1", "U2", "u2.txt", b"x", description="用户2数据")
        results = kb.search_knowledge("T1", "U1", "数据")
        file_ids = [r["file_id"] for r in results]
        # U1 不应看到 U2 的文件
        u2_meta = kb.get_file_meta_cached(
            next(m.file_id for m in kb._meta_cache.values() if m.owner_id == "U2")
        )
        assert u2_meta.file_id not in file_ids

    def test_search_includes_global(self, kb):
        kb.add_file("T1", "admin", "policy.pdf", b"x", scope="global",
                     description="公司政策", is_admin=True)
        results = kb.search_knowledge("T1", "U1", "政策")
        assert len(results) == 1
        assert results[0]["filename"] == "policy.pdf"

    def test_search_limit(self, kb):
        for i in range(10):
            kb.add_file("T1", "U1", f"file{i}.txt", b"x", description=f"数据文件{i}")
        results = kb.search_knowledge("T1", "U1", "数据", limit=3)
        assert len(results) == 3
