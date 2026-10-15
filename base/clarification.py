"""Small, deterministic clarification prompts for underspecified public requests."""
import re

def public_business_clarification(query):
    text=str(query or '').strip()
    if re.search(r'(?:转账|汇款).{0,40}(?:手续费|费用|收几|多少钱|唯一金额)',text) and re.search(r'(?:没(?:有)?确定|未确定|没提供|没说|都没有|都没)',text):
        return '查询转账费用需要明确转出银行、办理渠道和转账金额。请补充这些条件；条件不全时无法给出唯一费用。'
    if re.search(r'网点.{0,24}(?:几点|营业|开门)',text) and re.search(r'(?:最近|附近|楼下|没有网点名|没提供网点|没说网点)',text):
        return '请提供网点名称或所在城市、区县。本系统不读取实时位置，也没有实时网点营业状态；营业时间请以该网点官方信息为准。'
    return None
