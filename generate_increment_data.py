# -*- coding: utf-8 -*-
"""生成增量训练数据：委婉表述 + 短词的"业务咨询"样本，修复 BERT 意图分类盲区。

盲区现象：BERT 把"我想知道利率表""利率表""我想了解大额存单"误判为闲聊/账户敏感，
根因是训练数据里缺少委婉表述和短词。本脚本补充这类样本。

用法：
    python generate_increment_data.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI

from base.config import config

TARGET = 400  # 生成条数
BATCH = 40

PROMPT_TEMPLATE = """你是一个银行智能客服意图分类数据生成器。请生成 {num} 条"业务咨询"类别的用户查询文本。

【重点要求：使用委婉表述和短词】
1. 委婉/口语化的提问方式，例如：
   - "我想知道当前银行的利率表"
   - "我想了解一下大额存单的起存金额"
   - "麻烦问下定期存款有哪几种存期"
   - "请问一下存款保险能赔多少"
   - "我想看看现在活期存款的利率"
2. 短词提问，例如：
   - "利率表"、"大额存单"、"存单"、"存期"、"整存整取"、"零存整取"、"通知存款"

【业务范围】存款产品、利率、存期、起存金额、开户、挂失、转账限额、存款保险、提前支取、自动转存等

【要求】
1. 每条查询口语化、多样化，避免重复
2. 输出 JSON 数组，每个元素格式：{{"query": "查询文本", "label": "业务咨询"}}
3. 只输出 JSON 数组，不要任何解释文字或 markdown 代码块

输出："""


def call_llm(client, prompt):
    completion = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=4000,
    )
    return completion.choices[0].message.content


def parse_json_array(text):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find('['), text.rfind(']')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


def main():
    client = OpenAI(api_key=config.DASHSCOPE_API_KEY, base_url=config.DASHSCOPE_BASE_URL)
    data, seen = [], set()
    while len(data) < TARGET:
        num = min(BATCH, TARGET - len(data))
        try:
            resp = call_llm(client, PROMPT_TEMPLATE.format(num=num))
            items = parse_json_array(resp)
            if not items:
                print("解析失败，重试...", flush=True)
                continue
            for it in items:
                q = (it.get('query') or '').strip()
                if q and len(q) >= 2 and q not in seen:
                    seen.add(q)
                    data.append({"query": q, "label": "业务咨询"})
            print(f"已生成 {len(data)}/{TARGET}", flush=True)
        except Exception as e:
            print(f"调用失败：{str(e)[:80]}，重试...", flush=True)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'rag_qa', 'classify_data', 'finance_increment.jsonl')
    with open(out, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f"增量数据 {len(data)} 条已保存到 {out}")


if __name__ == '__main__':
    main()
