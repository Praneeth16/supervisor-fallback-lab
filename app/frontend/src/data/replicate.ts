export interface ReplicateStep {
  title: string;
  command: string;
  note: string;
}

// The lab rerun steps. Edit this file when the steps change; the Replicate page reads it.
export const REPLICATE_STEPS: ReplicateStep[] = [
  {
    title: "Edit the lab configuration",
    command: "lab.yaml",
    note: "Set the workspace profile, warehouse, catalog, schema prefix, brand, model names and the scope lists.",
  },
  {
    title: "Set up the scripts and tracing",
    command: "make setup tracing",
    note: "Installs the Python environment and creates the MLflow experiment that stores traces in Unity Catalog.",
  },
  {
    title: "Create the Delta tables",
    command: "make data",
    note: "Builds the schemas from the industry data model, fills them with synthetic data and adds metric views and a dashboard.",
  },
  {
    title: "Create the two curated Genie Agents",
    command: "make agents",
    note: "Creates the subscribers and revenue agent and the content and viewing agent through the Genie Workbench app.",
  },
  {
    title: "Write the scope into Genie One",
    command: "make scope",
    note: "Renders the scope from lab.yaml into the Genie One instructions and skill.",
  },
  {
    title: "Deploy the custom text to SQL agent",
    command: "make agent",
    note: "Deploys the fallback agent for Supervisor B. Its table allowlist is enforced in code.",
  },
  {
    title: "Create the two supervisors",
    command: "make supervisors",
    note: "Creates Supervisor A with Genie One as fallback and Supervisor B with the custom agent as fallback.",
  },
  {
    title: "Run the benchmark",
    command: "make eval",
    note: "Runs the questions against both supervisors, scores them with the judges and writes the results tables.",
  },
  {
    title: "Copy the Unity Gateway usage",
    command: "make gateway",
    note: "Run this about an hour after the benchmark. It copies the model and MCP calls of the run into the lab schema.",
  },
  {
    title: "Deploy this app",
    command: "make app",
    note: "Builds the frontend and deploys this Databricks App with the warehouse and endpoints from lab.yaml.",
  },
];
