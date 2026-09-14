from sklearn.ensemble import RandomForestRegressor


_RF_PARAMS = {
    "n_estimators", "criterion", "max_depth", "min_samples_split",
    "min_samples_leaf", "min_weight_fraction_leaf", "max_features",
    "max_leaf_nodes", "min_impurity_decrease", "bootstrap", "oob_score",
    "random_state", "n_jobs", "verbose", "warm_start", "ccp_alpha",
    "max_samples",
}


def create_random_forest(seed: int, hyperparameters):
    
    
    # OOB estimates provide a real tree-count curve for the training-result
    # page.  A forest still remains a one-shot estimator; this is only an
    # additional diagnostic and is disabled automatically for bootstrap=False.
    params = {"n_estimators": 100, "random_state": seed, "n_jobs": 1, "oob_score": True}
    if hyperparameters:
        params.update((k, v) for k, v in hyperparameters.items() if k in _RF_PARAMS)
    if params.get("max_depth") == 0:
        params["max_depth"] = None
    if params.get("bootstrap") is False:
        params["oob_score"] = False
    return RandomForestRegressor(**params)
