from pathlib import Path

def test_home_has_no_quick_cards_or_file_banner():
    s=Path("index.html").read_text(encoding="utf-8")
    for text in ["分析当前水风险","读取 ESG 报告","压力情景分析","已加入本次分析","id=\"fileChip\""]:
        assert text not in s
    assert "welcome-intro" in s
    assert "composer" in s
