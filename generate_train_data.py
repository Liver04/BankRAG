# -*- coding: utf-8 -*-
"""用 LLM 生成金融意图五分类训练数据（query + label），保存为 JSONL。

用法：
    python generate_train_data.py --per-category 400   # 每类 400 条，共 2000 条
    python generate_train_data.py --per-category 20    # 先小量测试
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI

from base.config import config

# 五类意图及其定义（用于生成数据的提示词）
CATEGORIES = {
    "闲聊": "问候、寒暄、身份询问、感谢、道别等非业务性对话，例如'你好''在吗''谢谢'",
    "业务咨询": "关于存款产品、利率、存期、开户、挂失、转账限额、存款保险等银行业务的正常咨询",
    "收益预测": "要求推荐产品、比较收益高低、询问'哪个赚得多/保本吗/稳赚吗/能赚多少'等涉及投资建议的诉求",
    "投诉": "投诉、差评、举报、表达不满、要求赔偿、质疑服务态度等",
    "账户敏感": "涉及个人账户余额查询、密码、身份证号、卡号、向指定账户转账等敏感操作",
}

BATCH_SIZE = 40  # 每批生成的条数


def build_prompt(category, desc, num):
    return f"""你是一个银行智能客服意图分类数据生成器。请生成 {num} 条"{category}"类别的用户查询文本。

【类别定义】
{category}：{desc}

【要求】
1. 每条查询要口语化、多样化、贴近真实银行客户提问，尽量避免重复或雷同
2. 输出 JSON 数组，每个元素格式：{{"query": "查询文本", "label": "{category}"}}
3. 只输出 JSON 数组本身，不要任何解释文字、不要 markdown 代码块

输出："""


def call_llm(client, prompt):
    completion = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,   # 提高多样性
        max_tokens=4000,
    )
    return completion.choices[0].message.content


def parse_json_array(text):
    """从 LLM 返回文本中提取 JSON 数组。"""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--per-category', type=int, default=400)
    args = parser.parse_args()

    client = OpenAI(api_key=config.DASHSCOPE_API_KEY, base_url=config.DASHSCOPE_BASE_URL)

    all_data = []
    seen = set()

    for category, desc in CATEGORIES.items():
        collected = 0
        print(f"生成类别：{category}", flush=True)
        while collected < args.per_category:
            num = min(BATCH_SIZE, args.per_category - collected)
            try:
                resp = call_llm(client, build_prompt(category, desc, num))
                items = parse_json_array(resp)
                if not items:
                    print(f"  [解析失败] 重试...", flush=True)
                    continue
                for item in items:
                    q = (item.get('query') or '').strip()
                    if q and len(q) >= 2 and q not in seen:
                        seen.add(q)
                        all_data.append({"query": q, "label": category})
                        collected += 1
                print(f"  已收集 {collected}/{args.per_category}", flush=True)
            except Exception as e:
                print(f"  [调用失败] {str(e)[:80]}，重试...", flush=True)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rag_qa', 'classify_data')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'finance_intent_train.jsonl')
    with open(out_path, 'w', encoding='utf-8') as f:
        for item in all_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

    stat = Counter(item['label'] for item in all_data)
    print(f"\n生成完成，共 {len(all_data)} 条")
    for cat, n in stat.items():
        print(f"  {cat}: {n} 条")
    print(f"保存到：{out_path}")


if __name__ == '__main__':
    main()
