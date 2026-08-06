# backend/tests/test_document_parser.py
from app.services.document_parser import parse_text, split_chunks

def test_split_chunks_basic():
    text = "段落一。" * 200
    chunks = split_chunks(text, chunk_size=100)
    assert len(chunks) > 1
    assert "段落一" in chunks[0]

def test_short_text_not_split():
    chunks = split_chunks("简短文本", chunk_size=500)
    assert len(chunks) == 1

def test_parse_markdown():
    # parse_text 接收 bytes 内容
    assert "标题" in parse_text("# 标题\n正文".encode(), "md")

def test_markdown_header_split():
    text = "# 第一章\n## 第一节\n内容A\n## 第二节\n内容B"
    chunks = split_chunks(text, ext="md")
    assert len(chunks) >= 2
    assert "第一章" in chunks[0]
