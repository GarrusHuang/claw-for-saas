"""SecretRedactor 单元测试。"""

import pytest
from core.secret_redactor import SecretRedactor


class TestCollectFromSettings:
    """Settings 收集测试。"""

    def test_collect_api_key(self):
        class FakeSettings:
            llm_api_key = "sk-1234567890abcdef"
            auth_jwt_secret = ""
        redactor = SecretRedactor()
        redactor.collect_from_settings(FakeSettings())
        assert "[REDACTED_API_KEY]" in redactor.redact("key is sk-1234567890abcdef")

    def test_collect_jwt_secret(self):
        class FakeSettings:
            llm_api_key = ""
            auth_jwt_secret = "my-super-secret-jwt-key-12345"
        redactor = SecretRedactor()
        redactor.collect_from_settings(FakeSettings())
        result = redactor.redact("jwt: my-super-secret-jwt-key-12345")
        assert "my-super-secret-jwt-key-12345" not in result
        assert "[REDACTED_JWT_SECRET]" in result

    def test_skip_not_needed_default(self):
        """默认值 'not-needed' 不应被收集。"""
        class FakeSettings:
            llm_api_key = "not-needed"
            auth_jwt_secret = ""
        redactor = SecretRedactor()
        redactor.collect_from_settings(FakeSettings())
        assert redactor.redact("not-needed") == "not-needed"

    def test_skip_short_value(self):
        """短于 8 字符的值不应被收集。"""
        class FakeSettings:
            llm_api_key = "short"
            auth_jwt_secret = ""
        redactor = SecretRedactor()
        redactor.collect_from_settings(FakeSettings())
        assert redactor.redact("short") == "short"


class TestRedactLiterals:
    """字面值替换测试。"""

    def test_exact_replacement(self):
        redactor = SecretRedactor()
        redactor.add_secret("my-secret-value-123", "DB_PASS")
        result = redactor.redact("Database password is my-secret-value-123")
        assert "my-secret-value-123" not in result
        assert "[REDACTED_DB_PASS]" in result

    def test_multiple_secrets(self):
        redactor = SecretRedactor()
        redactor.add_secret("secret-aaa-bbb", "FIRST")
        redactor.add_secret("secret-ccc-ddd", "SECOND")
        result = redactor.redact("first=secret-aaa-bbb second=secret-ccc-ddd")
        assert "secret-aaa-bbb" not in result
        assert "secret-ccc-ddd" not in result

    def test_longer_secret_first(self):
        """长 secret 应先被替换，避免短 secret 部分匹配。"""
        redactor = SecretRedactor()
        redactor.add_secret("abcdefghij", "SHORT")
        redactor.add_secret("abcdefghijklmnop", "LONG")
        result = redactor.redact("value=abcdefghijklmnop")
        assert "[REDACTED_LONG]" in result

    def test_skip_too_short_add_secret(self):
        redactor = SecretRedactor()
        redactor.add_secret("abc", "SHORT")  # < 5 chars, should be skipped
        assert redactor.redact("abc") == "abc"


class TestRedactPatterns:
    """正则模式匹配测试。"""

    def test_bearer_token(self):
        redactor = SecretRedactor()
        result = redactor.redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature")
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "[REDACTED]" in result

    def test_openai_api_key(self):
        redactor = SecretRedactor()
        result = redactor.redact("OPENAI_API_KEY=sk-abcdefghij1234567890abcdefghij")
        assert "sk-abcdefghij1234567890abcdefghij" not in result

    def test_aws_access_key(self):
        redactor = SecretRedactor()
        result = redactor.redact("aws_key=AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED_AWS_KEY]" in result

    def test_password_key_value(self):
        redactor = SecretRedactor()
        result = redactor.redact("password=mysuperpassword123")
        assert "mysuperpassword123" not in result
        assert "password=[REDACTED]" in result

    def test_secret_key_value(self):
        redactor = SecretRedactor()
        result = redactor.redact("secret: my_secret_value_456")
        assert "my_secret_value_456" not in result


class TestEdgeCases:
    """边界情况测试。"""

    def test_empty_string(self):
        redactor = SecretRedactor()
        assert redactor.redact("") == ""

    def test_none_like_empty(self):
        redactor = SecretRedactor()
        assert redactor.redact("") == ""

    def test_no_secrets_unchanged(self):
        redactor = SecretRedactor()
        text = "This is a normal log message with no secrets."
        assert redactor.redact(text) == text

    def test_no_false_positive_normal_text(self):
        """普通文本不应被误脱敏。"""
        redactor = SecretRedactor()
        text = "The function returned 42 items successfully."
        assert redactor.redact(text) == text
