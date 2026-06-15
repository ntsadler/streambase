# Streambase Data

This folder is for non-private reference data that can be committed, such as `band_references.json`.

Private working data is written to `local_data/` by default:

- `streambase.sqlite`
- `report.json`
- `playlists_raw.json`
- CSV exports

Override the private data directory with:

```bash
export STREAMBASE_DATA_DIR="/path/to/private/streambase-data"
```
