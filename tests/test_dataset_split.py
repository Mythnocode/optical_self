import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from frontend_pyside.app.workbench_payloads import explain_job_failure
from machine_learning.datasets.splitter import (
    resolve_training_splits,
    split_ids,
    too_few_samples_message,
)


def test_split_ids_keeps_three_nonempty_parts_for_small_sets():
    for count in (3, 5, 8, 16, 50):
        train, validation, test = split_ids(
            [f"s{i}" for i in range(count)], 0.7, 0.15, seed=42
        )
        assert train and validation and test
        assert len(train) + len(validation) + len(test) == count


def test_resolve_training_splits_rebuilds_empty_validation():
    sample_ids = [f"s{i}" for i in range(5)]
    train, validation, test = resolve_training_splits(
        sample_ids,
        sample_ids,
        [],
        [],
        seed=7,
    )
    assert train and validation and test
    assert sorted(train + validation + test) == sorted(sample_ids)


def test_too_few_samples_message_tells_user_what_to_do():
    text = too_few_samples_message(5)
    assert "5 条" in text
    assert "数据管理" in text
    assert "train" not in text.lower()
    assert "validation" not in text.lower()
    assert "test" not in text.lower()


def test_explain_job_failure_rewrites_legacy_split_error():
    text = explain_job_failure("数据集切分后至少需要非空 train/validation/test")
    assert "数据管理" in text
    assert "学不成" in text
    assert "train/validation/test" not in text
