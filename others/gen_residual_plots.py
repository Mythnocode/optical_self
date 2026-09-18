# -*- coding: utf-8 -*-
"""两个模型的残差图：残差(预测-真实) vs 真实仿真值，横向 0 线 + 误差带标注。"""
import json
import urllib.request
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from matplotlib import font_manager
    for cand in ("SimHei", "Microsoft YaHei"):
        fp = font_manager.findfont(cand, fallback_to_default=False)
        if fp and "default" not in fp.lower():
            font_manager.fontManager.addfont(fp)
            plt.rcParams["font.sans-serif"] = [cand]
            break
    plt.rcParams["axes.unicode_minus"] = False
except Exception:
    pass

DATASET = r"D:\optical_ml_workspace\user_data\datasets\dataset-479db61d7ed4\samples.jsonl"
MANIFEST = r"D:\optical_ml_workspace\user_data\datasets\dataset-479db61d7ed4\manifest.json"
BASE = "http://127.0.0.1:8000/api/v1/models/{model}/predict"
OUT = r"D:\python\VP-Projects"

MODELS = [
    ("model-8f12628616e0", "rf", "coupling_efficiency", "耦合效率", "", "随机森林代理模型"),
    ("model-8eff6a9a78d2", "xgb", "coupling_loss_db", "耦合损耗", " dB", "XGBoost物理残差模型"),
]


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load_split_map():
    m = json.load(open(MANIFEST, encoding="utf-8"))
    split = {}
    for sid in m.get("train_ids") or []:
        split[sid] = "train"
    for sid in m.get("validation_ids") or []:
        split[sid] = "validation"
    for sid in m.get("test_ids") or []:
        split[sid] = "test"
    return split


def load_samples():
    rows = []
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            s = json.loads(line)
            if s.get("valid"):
                rows.append(s)
    return rows


def predict_all(model_id, samples, target):
    pred = {}
    for s in samples:
        try:
            resp = post(BASE.format(model=model_id),
                        {"model_id": model_id, "features": s["feature_values"]})
            data = resp.get("data") or resp
            preds = data.get("predictions") or {}
            pred[s["sample_id"]] = float(preds[target])
        except Exception:
            pred[s["sample_id"]] = float("nan")
    return pred


def make_residual(model_id, tag, target, target_cn, unit, model_cn):
    samples = load_samples()
    split_map = load_split_map()
    pred = predict_all(model_id, samples, target)

    actual, resid, split = [], [], []
    for s in samples:
        a = float(s["target_values"][target])
        p = pred.get(s["sample_id"], float("nan"))
        if np.isfinite(p):
            actual.append(a)
            resid.append(p - a)  # 预测 - 真实
            split.append(split_map.get(s["sample_id"], "?"))
    actual = np.asarray(actual)
    resid = np.asarray(resid)
    split = np.asarray(split)

    test_mask = split == "test"
    r_test = resid[test_mask]
    rmse = float(np.sqrt(np.mean(r_test ** 2))) if len(r_test) else float("nan")
    mae = float(np.mean(np.abs(r_test))) if len(r_test) else float("nan")
    maxe = float(np.max(np.abs(r_test))) if len(r_test) else float("nan")

    fig, ax = plt.subplots(figsize=(8.2, 5.8))
    colors = {"train": "#1f77b4", "validation": "#ff7f0e", "test": "#2ca02c"}
    split_cn = {"train": "训练集", "validation": "验证集", "test": "测试集(留出)"}
    for sp in ("train", "validation", "test"):
        m = split == sp
        if m.any():
            ax.scatter(actual[m], resid[m], s=30, c=colors[sp], label=split_cn[sp],
                       alpha=0.85, linewidths=0.5, edgecolors="white")

    ax.axhline(0, color="black", lw=1.0, ls="-", label="零残差线")
    # ±RMSE 误差带
    ax.axhspan(-rmse, rmse, color="grey", alpha=0.08)
    ax.axhline(rmse, color="red", lw=0.8, ls="--", alpha=0.7)
    ax.axhline(-rmse, color="red", lw=0.8, ls="--", alpha=0.7, label="±RMSE")

    ax.set_xlabel("真实仿真%s%s" % (target_cn, unit))
    ax.set_ylabel("残差（预测 - 真实）%s" % unit)
    ax.set_title("残差图 — %s" % model_cn)
    ax.legend(title="样本划分", loc="upper right")
    ax.grid(alpha=0.3)

    txt = "测试集 RMSE = %.4f\nMAE = %.4f\n最大|残差| = %.4f" % (rmse, mae, maxe)
    ax.text(0.03, 0.97, txt, transform=ax.transAxes, va="top", fontsize=10,
            bbox=dict(boxstyle="round,pad=0.4", fc="#f7f7f7", ec="grey", alpha=0.9))

    plt.tight_layout()
    path = r"%s\residual_%s.png" % (OUT, tag)
    plt.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path)
    print("  test(n=%d) RMSE=%.4f MAE=%.4f max|res|=%g" % (int(test_mask.sum()), rmse, mae, maxe))


if __name__ == "__main__":
    for model_id, tag, target, target_cn, unit, model_cn in MODELS:
        make_residual(model_id, tag, target, target_cn, unit, model_cn)
    print("done")
