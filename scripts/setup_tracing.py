"""Create the lab's MLflow experiment and store its traces in Unity Catalog.

Traces land in <catalog>.<prefix>lab as mlflow_experiment_trace_* tables, so they can be queried
with SQL and joined to Unity Gateway usage.
"""

import os

import mlflow
from databricks.sdk import WorkspaceClient
from labconfig import load_config, save_state, schema, sql
from mlflow.entities import UCSchemaLocation
from mlflow.tracing.enablement import set_experiment_trace_location


def main():
    cfg = load_config()
    ws = cfg["workspace"]
    os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = ws["warehouse_id"]
    mlflow.set_tracking_uri("databricks")

    user = WorkspaceClient(profile=ws["profile"]).current_user.me().user_name
    name = f"/Users/{user}/hoshi-fallback-lab"
    experiment = mlflow.get_experiment_by_name(name)
    experiment_id = experiment.experiment_id if experiment else mlflow.create_experiment(name)

    catalog, lab_schema = schema(cfg, "lab").split(".")
    sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{lab_schema}", cfg)
    set_experiment_trace_location(
        location=UCSchemaLocation(catalog_name=catalog, schema_name=lab_schema),
        experiment_id=experiment_id,
    )
    save_state(experiment_id=experiment_id, experiment_name=name, trace_schema=f"{catalog}.{lab_schema}")
    print(f"experiment {name} ({experiment_id}) traces -> {catalog}.{lab_schema}")


main()
