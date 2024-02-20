# Changelog
* Patches (X.X.1) are small or urgent bug fixes or changes that don't affect compatibility.
* Minor releases (X.1.X) are new features such as added functions or small changes that don't cause major compatibility issues.
* Major releases (1.X.X) are major new features or changes that break backward compatibility in a big way.

## [Latest](https://github.com/int-brain-lab/iblutil/commits/main) [1.8.0]

### Modified

- util.rrmdir returns list of deleted folders; added function should have been minor release

## [1.7.5]

### Added

- util.rrmdir: method to recursively delete empty folders

##  [1.7.4]

### Modified

- setup_logger: use unicode for LOG_FORMAT_STR

##  [1.7.3]

- setup_logger: simpler layout  
- setup_logger: check class of log.handler instance before accessing class-specific field

##  [1.7.2]

### Modified

- moved numba jit import down in the only function that uses it to improve stability of the environment
as llvmlite is known to cause issues with some configurations

##  [1.7.1]

### Added

- blake2b support for io.hashfile

### Modified

- improved readability of logs

## [1.7.0]

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
