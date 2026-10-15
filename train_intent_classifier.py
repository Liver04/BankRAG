# -*- coding: utf-8 -*-
"""训练金融意图五分类 BERT 模型（基于 bert-base-chinese 微调）。

用法：
    python train_intent_classifier.py --data rag_qa/classify_data/finance_intent_train.jsonl

说明：
    - 五分类：闲聊 / 业务咨询 / 收益预测 / 投诉 / 账户敏感
    - 模型保存到 rag_qa/models/finance_intent_classifier
"""
import argparse
import json
import os
import sys

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from transformers import BertForSequenceClassification, BertTokenizer, Trainer, TrainingArguments

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base.config import config
from base.logger import logger

# 五分类标签映射（顺序即 label id）
LABELS = ["闲聊", "业务咨询", "收益预测", "投诉", "账户敏感"]
LABEL_MAP = {label: i for i, label in enumerate(LABELS)}

PRE_TRAINED = os.path.join(config.MODELS_DIR, 'bert-base-chinese')
SAVE_PATH = os.path.join(config.MODELS_DIR, 'finance_intent_classifier')


def load_data(data_file):
    data = []
    with open(data_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get('label') in LABEL_MAP:
                data.append(item)
    texts = [item['query'] for item in data]
    labels = [LABEL_MAP[item['label']] for item in data]
    return texts, labels


def preprocess(tokenizer, texts, labels):
    encodings = tokenizer(texts, truncation=True, padding=True, max_length=128, return_tensors="pt")
    return encodings, labels


def create_dataset(encodings, labels):
    class Dataset(torch.utils.data.Dataset):
        def __init__(self, encodings, labels):
            self.encodings = encodings
            self.labels = labels

        def __getitem__(self, idx):
            item = {key: val[idx] for key, val in self.encodings.items()}
            item["labels"] = torch.tensor(self.labels[idx])
            return item

        def __len__(self):
            return len(self.labels)

    return Dataset(encodings, labels)


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    accuracy = (predictions == labels).mean()
    return {"accuracy": accuracy}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='rag_qa/classify_data/finance_intent_train.jsonl')
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=8)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available()
                          else "mps" if torch.mps.is_available() else "cpu")
    logger.info(f"使用设备: {device}")

    # 1. 加载数据
    texts, labels = load_data(args.data)
    logger.info(f"加载训练数据 {len(texts)} 条，标签分布: "
                f"{ {LABELS[i]: labels.count(i) for i in set(labels)} }")

    train_texts, val_texts, train_labels, val_labels = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels)

    # 2. tokenizer + 模型
    tokenizer = BertTokenizer.from_pretrained(PRE_TRAINED)
    model = BertForSequenceClassification.from_pretrained(PRE_TRAINED, num_labels=len(LABELS))
    model.to(device)

    train_encodings, train_labels = preprocess(tokenizer, train_texts, train_labels)
    val_encodings, val_labels = preprocess(tokenizer, val_texts, val_labels)
    train_dataset = create_dataset(train_encodings, train_labels)
    val_dataset = create_dataset(val_encodings, val_labels)

    # 3. 训练参数
    training_args = TrainingArguments(
        output_dir="intent_bert_results",
        save_total_limit=1,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        warmup_steps=100,
        weight_decay=0.01,
        logging_dir="./intent_bert_logs",
        logging_steps=10,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        fp16=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
    )

    # 4. 训练
    logger.info("开始训练五分类 BERT 模型...")
    trainer.train()

    # 6. 保存结果
    os.makedirs(SAVE_PATH, exist_ok=True)
    model.save_pretrained(SAVE_PATH)
    tokenizer.save_pretrained(SAVE_PATH)
    logger.info(f"模型保存到 {SAVE_PATH}")

    # 7. 评估并持久化
    predictions = trainer.predict(val_dataset)
    pred_labels = np.argmax(predictions.predictions, axis=-1)
    report = classification_report(val_labels, pred_labels, target_names=LABELS, output_dict=True)
    cm = confusion_matrix(val_labels, pred_labels)

    # 持久化评测结果（供 README/文档引用，不得删除）
    import json
    result = {
        "accuracy": float((pred_labels == val_labels).mean()),
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "dataset_size": {"train": len(train_texts), "val": len(val_texts)},
        "labels": LABELS,
    }
    result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intent_evaluation_results.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"评测结果保存到 {result_path}")

    logger.info("\n分类报告:\n" + classification_report(val_labels, pred_labels, target_names=LABELS))
    logger.info("\n混淆矩阵:\n" + str(cm))


if __name__ == '__main__':
    main()
