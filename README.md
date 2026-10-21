# CareLoop

CareLoop notices when an older adult living alone breaks their usual morning routine, using Ring doorbell events. It checks a camera snapshot with an Amazon Bedrock vision model, explains in plain language why the morning looks unusual, and escalates step by step: the person first, then family, then a neighbor.

> Work in progress for the Amazon developer hackathon (Ring track). Full README arrives in Phase 8.

## Quick start

```bash
make setup          # Python 3.11+ virtualenv, installs CareLoop and dev tools, creates .env
make lint && make test
make probe          # needs RING_ACCESS_TOKEN in .env (Ring Developer Playground > Generate Token)
```

## Status

See [docs/PROGRESS.md](docs/PROGRESS.md).

## License

MIT, see [LICENSE](LICENSE).
