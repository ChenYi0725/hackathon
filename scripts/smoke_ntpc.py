"""Opt-in public API smoke; no case documents, credentials or Bedrock calls."""
import json
from app.application.open_data import DatasetSearch, DatasetRead
from app.infrastructure.ntpc_open_data import NtpcOpenData


def main():
    adapter = NtpcOpenData()
    found = adapter.search(DatasetSearch(keyword='實價 樹林'))
    if not found['datasets']:
        raise SystemExit('No matching official datasets; inspect the current catalog.')
    dataset = found['datasets'][0]
    result = adapter.read(DatasetRead(dataset_id=dataset['dataset_id'], size=1))
    print(json.dumps(dict(title=dataset['title'], source_url=result['source_url'],
                          fetched_at=result['fetched_at'], count=len(result['records']),
                          fields=list(result['records'][0]) if result['records'] else []), ensure_ascii=False))


if __name__ == '__main__':
    main()
