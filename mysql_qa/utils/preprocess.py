# utils/preprocess.py
# 文本预处理：英文转小写 + jieba 分词。用于 BM25 索引构建与查询。
import jieba

from base.logger import logger


def preprocess_text(text):
    """预处理文本：转小写 + 分词，返回词列表（供 BM25 使用）。"""
    try:
        return jieba.lcut(text.lower())
    except AttributeError as e:
        logger.error(f"文本预处理失败: {e}")
        return []
