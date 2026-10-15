"""Contextual high-risk rules plus BERT. Quotation is never a blanket bypass."""
import os,re
from base.config import config
from base.safety import current_rate_query
class QueryClassifier:
    LABELS=['闲聊','业务咨询','收益预测','投诉','账户敏感']
    BUSINESS_KEYWORDS=['利率','利息','存款','存单','存期','存折','起存','开户','挂失','转账','汇款','身份证','手续费','储蓄','账户','密码']
    GREETING=re.compile(r'(?:你好|您好|hi|hello|在吗|在不在|有人吗|谢谢|再见|你是谁|你叫什么)[!！。？?，,\s]*',re.I)
    PII=re.compile(r'(?<!\d)(?:\d{15,19}[0-9Xx]?|1[3-9]\d{9})(?!\d)|(?:密码|验证码|卡号|身份证号)\s*(?:是|为|[:：])')
    ACTION=re.compile(r'(?:查(?:一下|看|询)?|导出|提供|发给我|告诉我).{0,12}(?:我的|我名下|他人|父亲|客户).{0,12}(?:余额|流水|明细|卡号|身份资料)|(?:我的|我名下|本人).{0,10}(?:余额|流水|明细|完整卡号)|(?:帮我|替我|为我|请执行)\s*(?:立即|直接|现在|执行)?(?:转账|汇款|登录|修改|重置|解绑|关闭|冻结|查(?:看|询)?我的)|(?:转账|汇款|打钱)到(?!底)')
    ADVICE=re.compile(r'推荐|预测|稳赚|保证收益|一定赚|保本|买哪个|怎么投资|收益最高|最赚钱|利息最多|回报最高|收益最好|哪个(?:收益|利息|利率)高|哪(?:个|种).{0,12}(?:划算|赚得多)|(?:替我|帮我|给我|为我).{0,12}(?:代选|挑选|挑一个|选一个|决定|配置资产)|适合我.{0,10}(?:产品|养老)|个人投资组合')
    IMPLICIT_ADVICE=re.compile(r'(?:所有钱|全部(?:资金|积蓄)|所有(?:资金|积蓄)).{0,12}(?:该|应该|放哪|选哪|买哪|替我)')
    COMPLAINT=re.compile(r'投诉|差评|举报|维权|被骗|欺诈|欺骗消费者|乱收费|态度(?:太)?差|态度不好|要求赔偿|亏钱|亏损|霸王条款|辱骂|刁难')
    PUBLIC=re.compile(r'流程|手续|规则|规定|材料|用途|定义|含义|概念|区别|公式|周期|起存|期限|最低|费率|手续费|收费目录|入口|渠道|时限|预留|漏缴|漏存|补存|中断缴存|漏了|身份证.*(?:开户|核验)|开户.*身份证')
    NEGATION=re.compile(r'(?:不需要|不要求|不提供|不要|不用|并非|不是|不做|不)(?:任何|具体|收益|在|再|你|您|进行|提供|做){0,2}$')
    def __init__(self,model_path=None,predictor=None):
        self.predictor=predictor;self.model=None
        if predictor is not None:return
        try:
            import torch
            from transformers import BertForSequenceClassification,BertTokenizer
            self.torch=torch;self.device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            path=model_path or os.path.join(config.MODELS_DIR,'finance_intent_classifier')
            self.tokenizer=BertTokenizer.from_pretrained(path,local_files_only=True)
            self.model=BertForSequenceClassification.from_pretrained(path,local_files_only=True).to(self.device).eval()
            labels=[self.model.config.id2label.get(i) for i in range(5)]
            if labels!=self.LABELS and labels!=['LABEL_'+str(i) for i in range(5)]:raise ValueError('model_label_order_mismatch')
        except Exception:self.model=None
    def _predict_bert(self,text):
        if self.predictor:return self.predictor(text)
        if self.model is None:return None
        x=self.tokenizer(text,truncation=True,padding=True,max_length=128,return_tensors='pt')
        with self.torch.no_grad():out=self.model(**{k:v.to(self.device) for k,v in x.items()})
        return self.LABELS[int(out.logits.argmax(dim=1).item())]
    @classmethod
    def _active(cls,pattern,text):
        for m in pattern.finditer(text):
            prefix=re.split(r'[，,。；;]|但是|不过|而是|然后|同时|但|却',text[:m.start()])[-1]
            if cls.NEGATION.search(re.sub(r'[“「"]','',prefix)):continue
            quoted=any(x.start()<=m.start()<x.end() for x in re.finditer(r'“[^”]*”|「[^」]*」|"[^"]*"',text))
            if quoted and re.search(r'含义|这个词|一词|概念|用语|二字|文章中的词|资料写着|来自广告',text) and not re.search(r'替我|代选|请执行|照着买|我的问题请回答',text):continue
            tail=text[m.end():m.end()+10]
            if pattern is cls.COMPLAINT and re.match(r'(?:受理|处理)?(?:的)?(?:流程|入口|渠道|材料|时限)|知识|宣传',tail) and not re.search(r'我要(?:提交|正式)?$|我要求$',prefix):continue
            yield m.group()
    def rule_category(self,query):
        text=query.strip()
        if self.PII.search(text):return '账户敏感'
        if re.search(r'绕过.{0,8}(?:核验|认证|验证)|跳过核验|免验证|假装通过认证|伪造身份|内幕信息|未公开客户资料',text):return '账户敏感'
        if re.search(r'(?:把|将).{0,12}(?:我的|我名下).{0,12}(?:冻结|转出|转走|关闭|销户)|(?:冻结|注销|关闭|修改).{0,8}(?:我的|本人)',text):return '账户敏感'
        clauses=re.split(r'[，,。；;]|但是|不过|而是|然后|同时|但|却',text)
        if any(self.ACTION.search(c) and not re.match(r'^(?:不要|不用|不需要)(?:查看|查询|查|提供|操作)',c.strip()) for c in clauses):return '账户敏感'
        if any(self._active(self.ADVICE,text)) or self.IMPLICIT_ADVICE.search(text) or re.search(r'替(?:我|他|她|客户).{0,12}(?:挑好|选好|代选|配置)|承诺.{0,8}(?:本金和收益|稳赚)',text):return '收益预测'
        if any(self._active(self.COMPLAINT,text)):return '投诉'
        if self.GREETING.fullmatch(text) or re.fullmatch(r'谢谢(?:解答|你的解答)?[，,]?(?:我)?暂时没有(?:其它|其他|业务)?问题了[。!！]?',text):return '闲聊'
        if current_rate_query(text):return '业务咨询'
        if re.search(r'(?:存款保险|被保险存款|投保银行).{0,40}(?:额度|限额|本息|合并|超限|受偿|赔偿)|(?:本息合并|最高偿付限额)',text):return '业务咨询'
        if re.search(r'(?:转账|汇款).{0,35}(?:手续费|费用|收几|多少钱|唯一金额)',text) and re.search(r'(?:没(?:有)?确定|未确定|没提供|没说|都没有|都没)',text):return '业务咨询'
        if re.search(r'网点.{0,20}(?:几点|营业|开门)',text) and re.search(r'(?:最近|附近|楼下|没有网点名|没提供网点|没说网点)',text):return '业务咨询'
        return None
    def predict_category(self,query):
        text=query.strip()
        rule=self.rule_category(text)
        if rule:return rule
        if current_rate_query(text):return '业务咨询'
        predicted=self._predict_bert(text)
        if predicted is None:return '未知'
        if self.PUBLIC.search(text) and any(k in text for k in self.BUSINESS_KEYWORDS) and not re.search(r'把.{0,12}发给我|直接操作|跳过核验|免验证',text):return '业务咨询'
        if predicted in ('账户敏感','收益预测','投诉'):return predicted
        if predicted in ('闲聊','业务咨询') and any(k in text for k in self.BUSINESS_KEYWORDS):return '业务咨询'
        return predicted
