# Data Sync Notebook (Manual Process)

`upload_data_files.ipynb` is a Jupyter notebook that generates JSON search documents for Azure AI Search to be used by the Natural Language Search API by extracting data from the `content` and `statistics` SQL Server databases, transforming it, and writing output files.

This is currently a **temporary manual process** and is expected to be replaced by an event-driven EES process under **EES-7166**.

## Requirements

- Python (not version-specific - this has been tested with 3.14.6)
- Access to the EES `content` and `statistics` SQL Server databases
- Access to the EES `search` Azure Storage accounts containing the `nl-search-dataset-documents` and `nl-search-filter-documents` containers
- Access to the EES Azure AI Search resources
- Jupyter-capable environment (VS Code works well, but not required)

Install dependencies from this folder:

```bash
cd tools/data-sync
pip install -r requirements.txt
```

## Config setup

Create your local config from the example:

```bash
cp config.example.ini config.ini
```

Update `config.ini` with your local environment values. Do **not** commit `config.ini` to version control.

Set the following values:

- `db_server_name` - Server name of the SQL Server database containing the `content` and `statistics` databases
- `api_key` - A 'Find and Use an API' subscription key for the DfE Azure OpenAI API subscription

### Optional filtering

By default, the notebook processes every publication/release version returned by the database. To restrict output to a subset, set the values of the optional `[filtering]` section of `config.ini`:

- `publication_ids` - CSV list of Publication IDs to include
- `release_version_ids` - CSV list of Release Version IDs to include

Leave these blank (or remove the `[filtering]` section entirely) to process everything.

## Run and outputs

Before running, remove any existing output files from `output/dataset_level` and `output/filter_level`.

Open and run `upload_data_files.ipynb`.

Look out for a Microsoft Entra ID interactive sign-in popup and complete authentication to allow the notebook to connect to the databases and continue.

The notebook writes output files under `output`:

- `dataset_level` -> upload files to `nl-search-dataset-documents`
- `filter_level` -> upload files to `nl-search-filter-documents`

Both containers are in the EES `search` Azure Storage Account.

Before uploading new files, make sure you:

1. Empty both target storage containers.
2. Reset the Azure AI Search index/indexers that use those container datasources.
