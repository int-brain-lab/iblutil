# iblutil
![CI workflow](https://github.com/int-brain-lab/iblrplate/actions/workflows/main.yaml/badge.svg?branch=main)
[![Coverage Status](https://coveralls.io/repos/github/int-brain-lab/iblrplate/badge.svg?branch=main)](https://coveralls.io/github/int-brain-lab/iblrplate?branch=main)

Small utilities with minimal dependencies, tests run on Python 3.10 and 3.13

## Installation 

```
pip install iblutil
```


## Contribution guide

Install the `requirements-dev.txt` dependencies.

Release checklist:
- Python tests pass ./iblutil/tests
- `ruff check` passes
- update `CHANGELOG.md`
- update version number in `./iblutil/__init__.py`
- PR to main
- release on github.com with tag `X.X.X`. This will trigger an upload to pypi
