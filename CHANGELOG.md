# Changelog
## [Latest](https://github.com/int-brain-lab/iblutil/commits/main) [1.7.1]

### Added

- bincount2D moved from ibllib.processing to iblutil.numerical

## [1.6.0]

### Added

- numerical.rcoeff function that computes pairwise Pearson correlation coefficients for matrices

## [1.5.0]

### Added

- method in spacer.Spacer for detecting signal times from a dictionary of TTL polarities and timestamps

## [1.4.0]

### Added

- CHANGELOG.md file added
- net package for communicating between acquisition PCs (3.9 support only)
- spacer module for task data alignment

### Modified

- optional deep copy of Bunch
- get_logger renamed to setup_logger; level defaults to NOTSET; level of handlers not set
