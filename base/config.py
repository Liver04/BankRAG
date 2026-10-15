# base/config.py
# 金融领域（银行存款客服）RAG 系统的全局配置。
# 说明：本配置从 edu_rag_code 的 config.py 迁移改造而来，关键改动：
#   1. collection_name 改为金融专属集合 finance_deposit_v1（不改动原 IT 数据）
#   2. valid_sources 从"学科"改为"文档类型"（product/rate_table/regulation/business_rule/faq）
#   3. 新增金融合规相关配置：disclaimer（免责声明）、rerank_threshold（重排阈值）
#   4. MODELS_DIR 支持环境变量覆盖，方便复用已有模型（软链接 / 复制到 rag_qa/models）

import configparser
import json
import os


def _read_local_secret(project_root, name):
    """Read a local-only key/value from local_secrets.env; never log its contents."""
    path = os.path.join(project_root, 'local_secrets.env')
    try:
        with open(path, encoding='utf-8') as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                if key.strip() == name:
                    return value.strip().strip('\"').strip("'")
    except OSError:
        return ''
    return ''


class Config:
    def __init__(self, config_file=None):
        # 创建配置解析器，启用扩展插值功能
        self.config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())

        # 项目根目录 = 当前文件上两级（qa_system/）
        self.PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))

        self.LOG_DIR = os.path.join(self.PROJECT_ROOT, 'logs')
        # 数据目录：rag_qa/data，金融知识库放在 rag_qa/data/finance 下
        self.DATA_DIR = os.path.join(self.PROJECT_ROOT, 'rag_qa', 'data')
        # 模型目录：默认项目内 rag_qa/models，可用环境变量 MODELS_DIR 覆盖。
        # 复用已有模型时，把 edu_rag_code 的 models 目录软链接/复制到此处即可，无需重新下载。
        self.MODELS_DIR = os.getenv('MODELS_DIR', os.path.join(self.PROJECT_ROOT, 'rag_qa', 'models'))

        if config_file is None:
            config_file = os.path.join(self.PROJECT_ROOT, 'config.ini')
        self.config.read(config_file, encoding='utf-8')

        # ---------------- MySQL 配置 ----------------
        self.MYSQL_HOST = os.getenv('MYSQL_HOST', self.config.get('mysql', 'host', fallback='localhost'))
        self.MYSQL_PORT = int(os.getenv('MYSQL_PORT', self.config.getint('mysql', 'port', fallback=3307)))
        self.MYSQL_USER = os.getenv('MYSQL_USER', self.config.get('mysql', 'user', fallback='bank_rag'))
        self.MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', self.config.get('mysql', 'password', fallback=''))
        self.MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', self.config.get('mysql', 'database', fallback='bank_rag'))

        # ---------------- Redis 配置 ----------------
        self.REDIS_HOST = os.getenv('REDIS_HOST', self.config.get('redis', 'host', fallback='localhost'))
        self.REDIS_PORT = int(os.getenv('REDIS_PORT', self.config.get('redis', 'port', fallback=6379)))
        self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', self.config.get('redis', 'password', fallback=''))
        self.REDIS_DB = int(os.getenv('REDIS_DB', self.config.get('redis', 'db', fallback=1)))

        # ---------------- Milvus 配置 ----------------
        self.MILVUS_HOST = os.getenv('MILVUS_HOST', self.config.get('milvus', 'host', fallback='localhost'))
        self.MILVUS_PORT = os.getenv('MILVUS_PORT', self.config.get('milvus', 'port', fallback='19530'))
        # Milvus 数据库名：使用默认库 default，避免额外建库
        self.MILVUS_DATABASE_NAME = os.getenv('MILVUS_DATABASE_NAME',
                                              self.config.get('milvus', 'database_name', fallback='default'))
        # 金融集合名：与原 IT 集合隔离，互不影响
        self.MILVUS_COLLECTION_NAME = os.getenv('MILVUS_COLLECTION_NAME',
                                                self.config.get('milvus', 'collection_name',
                                                                fallback='finance_deposit_v1'))

        # ---------------- LLM 配置 ----------------
        self.LLM_MODEL = self.config.get('llm', 'model', fallback='qwen-plus')
        # API Key 仅从进程环境或本地忽略文件读取，不提供源码默认值。
        self.DASHSCOPE_API_KEY = (os.getenv('DASHSCOPE_API_KEY')
                                  or _read_local_secret(self.PROJECT_ROOT, 'DASHSCOPE_API_KEY'))
        self.DASHSCOPE_BASE_URL = self.config.get('llm', 'dashscope_base_url',
                                                  fallback='https://dashscope.aliyuncs.com/compatible-mode/v1')

        # ---------------- 检索参数 ----------------
        self.PARENT_CHUNK_SIZE = self.config.getint('retrieval', 'parent_chunk_size', fallback=1200)
        self.CHILD_CHUNK_SIZE = self.config.getint('retrieval', 'child_chunk_size', fallback=300)
        self.CHUNK_OVERLAP = self.config.getint('retrieval', 'chunk_overlap', fallback=50)
        self.RETRIEVAL_K = self.config.getint('retrieval', 'retrieval_k', fallback=10)
        self.CANDIDATE_M = self.config.getint('retrieval', 'candidate_m', fallback=3)
        # 金融新增：rerank 最低相关性阈值。
        # bge-reranker-large 的分数 > 0 视为相关、< 0 视为不相关；该值需在评测集上进一步调优。
        self.RERANK_THRESHOLD = self.config.getfloat('retrieval', 'rerank_threshold', fallback=0.15)
        # FAQ 精确匹配阈值（BM25 softmax 归一化后的分数，>= 该值视为命中标准答案）
        self.FAQ_THRESHOLD = self.config.getfloat('retrieval', 'faq_threshold', fallback=0.85)

        # ---------------- 金融应用配置 ----------------
        # 文档类型（替代原"学科"概念）
        self.VALID_SOURCES = json.loads(
            self.config.get('app', 'valid_sources',
                            fallback='["product", "rate_table", "regulation", "business_rule", "faq"]'))
        # 转人工客服电话（演示用，可填任意占位号）
        self.CUSTOMER_SERVICE_PHONE = self.config.get('app', 'customer_service_phone', fallback='95588')
        # 免责声明：回答末尾强制追加。学习项目自拟，生产环境须由法务审核定稿。
        self.DISCLAIMER = self.config.get(
            'app', 'disclaimer',
            fallback='以上内容仅供参考，不构成投资建议或收益承诺。'
                     '存款产品受《存款保险条例》保障，具体利率、规则及收费标准以银行最新官方公布为准；'
                     '如涉及理财/基金产品，请注意：理财非存款、产品有风险、投资需谨慎。')

        self.LOG_FILE = os.path.join(self.LOG_DIR, 'app.log')


# 模块级单例，供 logger 等模块直接 import 使用
config = Config()

if __name__ == '__main__':
    conf = Config()
    print('collection_name =', conf.MILVUS_COLLECTION_NAME)
    print('valid_sources   =', conf.VALID_SOURCES)
    print('models_dir      =', conf.MODELS_DIR)
    print('disclaimer      =', conf.DISCLAIMER)
