# -*- coding: utf-8 -*-
"""残差直方图 + 学习曲线（两个模型各两张）。

  * residual_hist_<tag>.png  —— 残差(预测-真实)直方图，0 线 + 均值/标准差/RMSE 标注
  * learning_curve_<tag>.png —— RF 用 OOB RMSE vs 树数；XGBoost 用验证 RMSE vs 迭代
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
MODEL_DIR = r"D:\optical_ml_workspace\user_data\models"
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


def residuals(model_id, samples, target):
    pred = predict_all(model_id, samples, target)
    split_map = load_split_map()
    res, test_res = [], []
    for s in samples:
        a = float(s["target_values"][target])
        p = pred.get(s["sample_id"], float("nan"))
        if np.isfinite(p):
            r = p - a
            res.append(r)
            if split_map.get(s["sample_id"]) == "test":
                test_res.append(r)
    return np.asarray(res), np.asarray(test_res)


def make_hist(model_id, tag, target, target_cn, unit, model_cn):
    samples = load_samples()
    res, test_res = residuals(model_id, samples, target)
    mean = float(np.mean(res))
    std = float(np.std(res))
    rmse_test = float(np.sqrt(np.mean(test_res ** 2))) if len(test_res) else float("nan")

    fig, ax = plt.subplots(figsize=(7.6, 5.4))
    ax.hist(res, bins=24, color="#4C72B0", edgecolor="white", alpha=0.85)
    ax.axvline(0, color="black", lw=1.2, label="零残差")
    ax.axvline(mean, color="red", lw=1.2, ls="--", label="均值 %.4f" % mean)
    ax.set_xlabel("残差（预测 - 真实）%s" % unit)
    ax.set_ylabel("样本数")
    ax.set_title("残差分布 — %s" % model_cn)
    ax.legend(loc="upper right")

    txt = "样本数 = %d\n均值 = %.4f\n标准差 = %.4f\n测试集 RMSE = %.4f" % (len(res), mean, std, rmse_test)
    ax.text(0.03, 0.97, txt, transform=ax.transAxes, va="top", fontsize=10,
            bbox=dict(boxstyle="round,pad=0.4", fc="#f7f7f7", ec="grey", alpha=0.9))
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    path = r"%s\residual_hist_%s.png" % (OUT, tag)
    plt.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path, "| mean=%.4f std=%.4f testRMSE=%.4f" % (mean, std, rmse_test))


def make_learning_curve(model_id, tag, target_cn, unit, model_cn):
    m = json.load(open(r"%s\%s\manifest.json" % (MODEL_DIR, model_id), encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    test_rmse = (m.get("test_metrics") or {}).get("rmse")

    oob = m.get("oob_error_curve")
    hist = m.get("training_history") or {}
    if oob:
        curve = np.asarray(oob, dtype=float)
        x = np.arange(1, len(curve) + 1)
        ax.plot(x, curve, color="#4C72B0", lw=1.6, label="OOB RMSE（袋外误差）")
        ax.set_xlabel("随机森林树的数量")
        ax.set_title("学习曲线 — %s（OOB RMSE）" % model_cn)
    elif hist:
        # 取第一个验证集的 rmse
        curve = None
        for name, metrics in hist.items():
            if isinstance(metrics, dict) and "rmse" in metrics:
                curve = np.asarray(metrics["rmse"], dtype=float)
                break
        if curve is None:
            print("  no rmse curve in history:", list(hist.keys()))
            return
        x = np.arange(1, len(curve) + 1)
        ax.plot(x, curve, color="#C44E52", lw=1.6, label="验证 RMSE")
        ax.set_xlabel("迭代次数")
        ax.set_title("学习曲线 — %s（验证 RMSE）" % model_cn)
    else:
        print("  no learning curve for", model_id)
        return

    if test_rmse is not None:
        ax.axhline(test_rmse, color="grey", lw=1.0, ls="--",
                   label="测试集 RMSE = %.4f" % test_rmse)
    ax.set_ylabel("RMSE（%s）%s" % (target_cn, unit))
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    path = r"%s\learning_curve_%s.png" % (OUT, tag)
    plt.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path, "| curve_len=%d final=%.4f testRMSE=%s" % (
        len(curve), float(curve[-1]), test_rmse))


if __name__ == "__main__":
    for model_id, tag, target, target_cn, unit, model_cn in MODELS:
        make_hist(model_id, tag, target, target_cn, unit, model_cn)
        make_learning_curve(model_id, tag, target_cn, unit, model_cn)
    print("done")
