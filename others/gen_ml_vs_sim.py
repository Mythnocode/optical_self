# -*- coding: utf-8 -*-
"""机器学习预测 vs 真实光学仿真 对比图（证明代理模型精度）。

数据来源：数据集 dataset-479db61d7ed4 的全部 90 条有效样本。
  * 真实值 = 每个样本 target_values（物理光学仿真算出的耦合效率 / 耦合损耗）
  * 预测值 = 调用平台 /models/{id}/predict 接口得到
每个模型出一张图：预测 vs 真实散点 + y=x 对角线 + 测试集 R²/MAE/RMSE 标注。
"""
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


def r2(y, p):
    ss_res = float(np.sum((np.asarray(y) - np.asarray(p)) ** 2))
    ss_tot = float(np.sum((np.asarray(y) - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")


def metrics(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return {
        "R2": r2(y, p),
        "MAE": float(np.mean(np.abs(y - p))),
        "RMSE": float(np.sqrt(np.mean((y - p) ** 2))),
        "max_err": float(np.max(np.abs(y - p))),
    }


def predict_all(model_id, samples, target):
    pred = {}
    for s in samples:
        sid = s["sample_id"]
        try:
            resp = post(BASE.format(model=model_id), {"model_id": model_id, "features": s["feature_values"]})
            data = resp.get("data") or resp
            preds = data.get("predictions") or {}
            pred[sid] = float(preds[target])
        except Exception as e:
            print("  predict err", sid, repr(e))
            pred[sid] = float("nan")
    return pred


def make_plot(model_id, tag, target, target_cn, unit, model_cn):
    samples = load_samples()
    split_map = load_split_map()
    pred = predict_all(model_id, samples, target)

    X = []  # actual
    Y = []  # predicted
    split = []
    for s in samples:
        actual = float(s["target_values"][target])
        p = pred.get(s["sample_id"], float("nan"))
        if np.isfinite(p):
            X.append(actual)
            Y.append(p)
            split.append(split_map.get(s["sample_id"], "?"))
    X = np.asarray(X)
    Y = np.asarray(Y)
    split = np.asarray(split)

    # 测试集（留出集）指标 —— 最诚实的精度证明
    test_mask = split == "test"
    m_test = metrics(X[test_mask], Y[test_mask]) if test_mask.any() else {}
    m_all = metrics(X, Y)

    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    colors = {"train": "#1f77b4", "validation": "#ff7f0e", "test": "#2ca02c"}
    split_cn = {"train": "训练集", "validation": "验证集", "test": "测试集(留出)"}
    for sp in ("train", "validation", "test"):
        m = split == sp
        if m.any():
            ax.scatter(X[m], Y[m], s=28, c=colors[sp], label=split_cn[sp], alpha=0.8, linewidths=0.5, edgecolors="white")

    lo = min(X.min(), Y.min())
    hi = max(X.max(), Y.max())
    pad = (hi - lo) * 0.05
    ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "k--", lw=1.0, label="理想一致 y=x")

    ax.set_xlabel("真实仿真%s%s" % (target_cn, unit))
    ax.set_ylabel("机器学习预测%s%s" % (target_cn, unit))
    ax.set_title("ML 预测 vs 真实仿真 — %s" % model_cn)
    ax.legend(title="样本划分", loc="lower right")

    txt = "测试集(留出) R^2 = %.4f\nMAE = %.4f   RMSE = %.4f\n全样本 R^2 = %.4f" % (
        m_test.get("R2", float("nan")), m_test.get("MAE", float("nan")),
        m_test.get("RMSE", float("nan")), m_all.get("R2", float("nan")))
    ax.text(0.05, 0.95, txt, transform=ax.transAxes, va="top", fontsize=10,
            bbox=dict(boxstyle="round,pad=0.4", fc="#f7f7f7", ec="grey", alpha=0.9))

    ax.grid(alpha=0.3)
    plt.tight_layout()
    path = r"%s\ml_vs_sim_%s.png" % (OUT, tag)
    plt.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path)
    print("  test(n=%d) R2=%.4f MAE=%.4f RMSE=%.4f | all(n=%d) R2=%.4f" % (
        int(test_mask.sum()), m_test.get("R2", float("nan")), m_test.get("MAE", float("nan")),
        m_test.get("RMSE", float("nan")), len(X), m_all.get("R2", float("nan"))))


if __name__ == "__main__":
    for model_id, tag, target, target_cn, unit, model_cn in MODELS:
        make_plot(model_id, tag, target, target_cn, unit, model_cn)
    print("done")
