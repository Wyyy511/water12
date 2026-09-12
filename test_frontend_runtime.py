from pathlib import Path

def test_no_removed_file_strip_reference():
    html = Path("index.html").read_text(encoding="utf-8")
    assert "$('#removeFile').onclick" not in html
    assert "attach: $('#attachBtn')" in html

def test_status_init_has_timeout_and_connection_states():
    html = Path("index.html").read_text(encoding="utf-8")
    assert "fetchJsonWithTimeout('/api/agent/status'" in html
    assert "DeepSeek 已配置" in html
    assert "DeepSeek 已连接" in html
    assert "DeepSeek 已配置 · 连接待确认" in html
