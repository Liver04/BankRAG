"""Full BERT CPU fine-tune on explicit group splits; never overwrite served weights."""
import argparse,json,os,random,time,hashlib
from pathlib import Path
import numpy as np
import torch
from transformers import BertTokenizer,BertForSequenceClassification,Trainer,TrainingArguments,DataCollatorWithPadding,set_seed
from sklearn.metrics import classification_report,confusion_matrix
LABELS=['闲聊','业务咨询','收益预测','投诉','账户敏感']
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--epochs',type=int,default=5);p.add_argument('--version',default='context_v2_1');args=p.parse_args()
    root=args.root;data=root/'rag_qa/classify_data'/args.version/'data.jsonl';out=root/'rag_qa/models'/('finance_intent_'+args.version+'_candidate')
    if out.exists():raise RuntimeError('candidate_path_exists; do not overwrite evidence')
    out.mkdir(parents=True);set_seed(20261013);torch.set_num_threads(8)
    rows=[json.loads(s) for s in data.read_text(encoding='utf-8').splitlines()];tr=[r for r in rows if r['split']=='train'];va=[r for r in rows if r['split']=='validation']
    assert not {r['semantic_group'] for r in tr}&{r['semantic_group'] for r in va}
    tok=BertTokenizer.from_pretrained(root/'rag_qa/models/bert-base-chinese',local_files_only=True)
    model=BertForSequenceClassification.from_pretrained(root/'rag_qa/models/bert-base-chinese',num_labels=5,id2label=dict(enumerate(LABELS)),label2id={v:i for i,v in enumerate(LABELS)},local_files_only=True)
    class Data(torch.utils.data.Dataset):
        def __init__(self,items):self.items=[dict(**tok(r['query'],truncation=True,max_length=128),labels=LABELS.index(r['label'])) for r in items]
        def __len__(self):return len(self.items)
        def __getitem__(self,i):return self.items[i]
    metrics=lambda p:{'accuracy':float((p.predictions.argmax(-1)==p.label_ids).mean())}
    training=TrainingArguments(output_dir=str(out/'checkpoints'),use_cpu=True,num_train_epochs=args.epochs,per_device_train_batch_size=8,per_device_eval_batch_size=16,learning_rate=2e-5,warmup_ratio=.1,weight_decay=.01,eval_strategy='epoch',save_strategy='epoch',save_total_limit=1,load_best_model_at_end=True,metric_for_best_model='eval_loss',report_to=[],seed=20261013,data_seed=20261013,logging_steps=10,dataloader_num_workers=0,disable_tqdm=True)
    trainer=Trainer(model=model,args=training,train_dataset=Data(tr),eval_dataset=Data(va),data_collator=DataCollatorWithPadding(tok),compute_metrics=metrics)
    started=time.time();print('CPU_TRAIN_START',len(tr),len(va),flush=True);trainer.train()
    pred=trainer.predict(Data(va));y=pred.label_ids;yp=pred.predictions.argmax(-1)
    trainer.save_model(str(out));tok.save_pretrained(str(out))
    result=dict(status='candidate_trained_not_promoted',device='cpu',full_encoder_finetuned=True,epochs=args.epochs,seconds=time.time()-started,train_rows=len(tr),validation_rows=len(va),semantic_group_overlap=0,data_sha256=hashlib.sha256(data.read_bytes()).hexdigest(),accuracy=float((y==yp).mean()),classification_report=classification_report(y,yp,labels=list(range(5)),target_names=LABELS,output_dict=True,zero_division=0),confusion_matrix=confusion_matrix(y,yp,labels=list(range(5))).tolist(),limits='Synthetic development validation; neither independent human labels nor blind generalization accuracy')
    (out/'training_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print('CPU_TRAIN_FINISHED',json.dumps({k:result[k] for k in ('status','seconds','accuracy')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
