# Changelog
* Patches (X.X.1) are small or urgent bug fixes or changes that don't affect compatibility.
* Minor releases (X.1.X) are new features such as added functions or small changes that don't cause major compatibility issues.
* Major releases (1.X.X) are major new features or changes that break backward compatibility in a big way.

## [Latest](https://github.com/int-brain-lab/iblutil/commits/main) [1.18.0] [YANKED]

### Added

- iblutil.random.sillyname: a module to create a 3 words (preferably silly) name with a collision probability of 1/80M. No expletives.

## [Latest](https://github.com/int-brain-lab/iblutil/commits/main) [1.18.1]

### Fixed

- build includes submodules but excludes tests.

## [Latest](https://github.com/int-brain-lab/iblutil/commits/main) [1.18.0] [YANKED]

### Added

- ruff

### Modified

- project moved to `pyproject.toml`
- handle truncated UDP echoes
- bugfix: incorrect message enum used in Services.stop

## [1.17.0]

### Modified

- upgrade minimum supported Python version to 3.10

## [1.16.0]

### Added

- io.binary.write_array: write array to binary file

## [1.15.0]

### Added

- io.binary.load_as_dataframe: read binary data as a Pandas DataFrame
- io.binary.convert_to_parquet: convert a binary file to Parquet

## [1.14.0]

### Added

- io.jsonable.load_task_jsonable: read and format iblrig raw data to a trials table Dataframe and a list of raw Bpod trials
- util.Listable: returns a typing class that is the union of input class and a sequence thereof

## [1.13.0]

### Added

- util.ensure_list: function returning input wrapped in list if not an iterator or a member of specific iterable classes

### Modified

- io.net.app.EchoProtocol.confirmed_send: more informative timeout error message

## [1.12.1]

### Modified

- Moved get_mac() to util

## [1.12.0]

### Added

- io.net.base.get_mac: function returning the machine's unique MAC address formatted according to IEEE 802 specifications

## [1.11.0]

### Added

- io.net.base.ExpStatus: standard enumeration for UDP experiment status messages
- io.net.base.is_success: function to determine if future resolved without cancellation or error
- io.params.FileLock: context manager for checking for file access flag file

### Modified

- io.net.base.Service: protocol versioning
- io.net.base.ExpMessage: support bitwise operations and iteration in 3.10

## [1.10.0]

### Added

- util.dir_size: method to determine size of directory in bytes

## [1.9.0]

### Added

- numerical.hash_uuids returns the hash of a collection of UUIDs

## [1.8.0]

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
