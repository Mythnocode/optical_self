from sklearn.ensemble import RandomForestRegressor


_RF_PARAMS = {
    "n_estimators", "criterion", "max_depth", "min_samples_split",
    "min_samples_leaf", "min_weight_fraction_leaf", "max_features",
    "max_leaf_nodes", "min_impurity_decrease", "bootstrap", "oob_score",
    "random_state", "n_jobs", "verbose", "warm_start", "ccp_alpha",
    "max_samples",
}


def create_random_forest(seed: int, hyperparameters):
    
    
    params = {"n_estimators": 100, "random_state": seed, "n_jobs": 1}
    if hyperparameters:
        params.update((k, v) for k, v in hyperparameters.items() if k in _RF_PARAMS)
    return RandomForestRegressor(**params)
