# Research workflows

## US.APP mutation research

```sh
python3 scripts/app_strategy_lab.py --db quant_dashboard.sqlite3 \
  --agents 2 --candidates 100 --providers local,nvidia,antigravity
```

The loop generates bounded proposals, evaluates them on chronological holdout slices, and writes run summaries plus the promoted parameter file locally. It does not provide a persistent learning-memory store.

## Reports and artifacts

Generated reports and run artifacts are local-only. They must not be committed because they may contain large datasets, runtime state, local paths, or account-related information.
