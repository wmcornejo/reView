# -*- coding: utf-8 -*-
"""Config class used for all reView projects.

Created on Sat Aug 15 15:47:40 2020

@author: travis
"""
import ast
import json
import logging

from functools import cached_property, lru_cache
from itertools import chain
from pathlib import Path

import h5py
import pandas as pd
import pyarrow as pa 

from pyarrow.parquet import ParquetFile

from reView import REVIEW_DATA_DIR
from reView.utils.constants import COMMON_REV_COLUMN_UNITS, SCALE_OVERRIDES
from reView.utils.functions import (
    deep_replace,
    get_project_defaults,
    load_project_configs,
    strip_rev_filename_endings,
)

pd.set_option("mode.chained_assignment", None)

logger = logging.getLogger(__name__)


DEFAULT_PROJECT = get_project_defaults()["rev"]
PROJECT_CONFIGS = load_project_configs()
PROJECT_NAMES = list(PROJECT_CONFIGS.keys())


def contains(pattern, patterns):
    """Check if a pattern contains any of a list of patterns.

    Parameters
    ----------
    pattern : str
        A string of characters.
    patterns : list | list-like
        A list of strings of characters.

    Returns
    -------
    bool : A boolean indicating if pattern contains any one of the strings in
           patterns.
    """
    pattern = str(pattern)
    patterns = [str(pat) for pat in patterns]
    return any(p in pattern for p in patterns)


def decode(df):
    """Decode the columns of a meta data object from a reV output."""
    def decode_single(x):
        """Try to decode a single value, pass if fail."""
        try:
            x = x.decode()
        except UnicodeDecodeError:
            x = "indecipherable"
        return x

    for c in df.columns:
        x = df[c].iloc[0]
        if isinstance(x, bytes):
            try:
                df[c] = df[c].apply(decode_single)
            except Exception:
                df[c] = None
                print("Column " + c + " could not be decoded.")
        elif isinstance(x, str):
            try:
                if isinstance(ast.literal_eval(x), bytes):
                    try:
                        self._obj[c] = self._obj[c].apply(
                            lambda x: ast.literal_eval(x).decode()
                        )
                    except Exception:
                        df[c] = None
                        print("Column " + c + " could not be decoded.")
            except:
                pass
    return df


def infer_capcol(fpath):
    """Infer the capacity column from a data frame (prefer ac)."""
    cols = read_rev(fpath, nrows=0).columns
    skippers = ["density", "turbine", "system"]
    capcols = [col for col in cols if "capacity" in col]
    capcols = [col for col in capcols if not contains(col, skippers)]
    if len(capcols) == 1:
        capcol = capcols[0]
    elif any("_ac" in col for col in capcols):
        capcol = [col for col in capcols if "_ac" in col][0]
    else:
        raise KeyError("Could not find capacity column")
    return capcol


def read_rev(fpath, nrows=None):
    """Infer the appropriate read method for a reV supply curve."""
    if Path(fpath).name.endswith("parquet"):
        if nrows:
            pf = ParquetFile(fpath)
            nrows = next(pf.iter_batches(batch_size=nrows)) 
            sc = pa.Table.from_batches([nrows]).to_pandas() 
        else:
            sc = pd.read_parquet(fpath)
    elif Path(fpath).name.endswith("csv"):
        sc = pd.read_csv(fpath, nrows=nrows)
    elif Path(fpath).name.endswith(".h5"):
        sc = pd.DataFrame(h5py.File(fpath)["meta"][:nrows])
        if sc.shape[0] > 0:
            sc = decode(sc)
    return sc


class Config:
    """Class for handling configuration variables."""

    _all_configs = {}
    REQUIREMENTS = {"directory"}

    def __new__(cls, project=DEFAULT_PROJECT):
        return cls._all_configs.setdefault(project, super().__new__(cls))

    def __init__(self, project=DEFAULT_PROJECT):
        """Initialize plotting object for a reV project."""
        self.project = project
        self._config = None
        self._check_valid_project_name()
        self._set_config()
        self._check_required_keys_exist()

    def __str__(self):
        msg = (
            f"<reView Config object: "
            f"project={self.project!r}, {len(self.files)} files>"
        )
        return msg

    def __repr__(self):
        return f"Config({self.project!r})"

    @property
    def capacity_column(self):
        """Return the most appropriate capacity column."""
        for _, fpath in self._project_files:
            break
        capcol = infer_capcol(fpath)
        return capcol

    @property
    def capacity_density(self):
        """Return capacity-dependent scaling information if available."""
        density = self._config.get("capacity_density", None)
        if density:
            density = float(density)
        return density

    @property
    def characterization_cols(self):
        """Return list of column names with characterization info."""
        return self._config.get("characterization_cols", [])

    @property
    def directory(self):
        """Return posix path for the project directory path."""
        return self._extract_fp_from_config("directory")

    @property
    def demand_data(self):
        """Return demand data if it exists."""
        return self._safe_read("demand_file")

    @property
    def eos(self):
        """Return capacity-dependent scaling information if available."""
        eos = self._config.get("eos", None)
        neos = {}
        for key, value in eos.items():
            neos[key] = ast.literal_eval(value)
        return neos

    @property
    def files(self):
        """Return a dictionary of scenario with full paths to files."""
        # TODO: If we need better performance, we may consider caching the
        #       output of this in a project-based class-level dictionary so
        #       that it can be quickly accessed when the config class is
        #       reinitialized
        return dict(self._project_files)

    @property
    def groups(self):
        """dict: Groups dictionary."""
        return self._config.get("groups", {})

    @property
    def low_cost_groups(self):
        """dict: Low-cost group options dictionary."""
        return self._config.get("low_cost_groups", {})

    @property
    def name_lookup(self):
        """Return file to name lookup dictionary."""
        return {str(v): k for k, v in dict(self._project_files).items()}

    @cached_property
    def options(self):
        """:obj:`pandas.DataFrame` or `None`: DataFrame containing
        variables as column names and values as rows, or `None` if the
        "var_file" key was not specified in the config.
        """
        return self._safe_read(
            "var_file", default_fp=self.directory / "variable_options.csv"
        )

    @cached_property
    def outputs(self):
        """Return a list of reView outputs derived in previous sessions."""
        output_dir = self.directory.joinpath("review_outputs")
        if output_dir.exists():
            outputs = list(output_dir.glob("*"))
        else:
            outputs = []
        return outputs

    @property
    def parameters(self):
        """dict: Parameters config dictionary."""
        return self._config.get("parameters", {})

    @classmethod
    @property
    def projects(cls):
        """Return names of available projects."""
        for name in PROJECT_CONFIGS:
            try:
                if any(cls(name)._project_files):
                    yield name
            except ValueError:
                continue

    @property
    def resolution(self):
        """Return capacity-dependent scaling information if available."""
        resolution = self._config.get("resolution", None)
        if resolution:
            resolution = int(resolution)
        return resolution

    @classmethod
    @property
    def sorted_projects(cls):
        """Return the sorted names of available projects."""
        return sorted(cls.projects)

    @property
    def sam(self):
        """Return SAM information if available."""
        return self._config.get("sam", None)

    @property
    def scales(self):
        """Return a titles dictionary with extra fields."""
        scales = self._config.get("scales", {})
        scales.update(SCALE_OVERRIDES)
        deep_replace(scales, {"na": None})
        return scales

    @property
    def scenarios(self):
        """Return just a list of scenario names."""
        return list(self.files.keys())

    @property
    def titles(self):
        """Return a titles dictionary with extra fields."""
        return self._config.get("titles", {})

    @property
    def units(self):
        """Return a units dictionary with extra fields."""
        provided_units = self._config.get("units", {})
        units = COMMON_REV_COLUMN_UNITS.copy()
        units.update(provided_units)
        return units

    @property
    def all_files(self):
        """:obj:`generator`: Generator of raw project files."""
        if self.options is not None and "file" in self.options:
            for file in self.options.file:
                if file.startswith("./"):
                    yield self.directory.joinpath(file).expanduser()
                else:
                    yield Path(file).expanduser()
        else:
            cfiles = self.directory.rglob("*.csv")
            pfiles = self.directory.rglob("*.parquet")
            hfiles = self.directory.rglob("*.h5")
            files = chain(cfiles, pfiles, hfiles)
            yield from files 

    def _check_required_keys_exist(self):
        """Ensure all required keys are present in config file."""
        missing = [
            req for req in self.REQUIREMENTS if self._config.get(req) is None
        ]

        if missing:
            error_message = (
                f"Config for project {self.project!r} missing the following "
                f"keys: {missing}"
            )
            logger.error(error_message)
            raise ValueError(error_message)

    def _check_valid_project_name(self):
        """Ensure project name is not None."""
        if self.project is None:
            raise ValueError("Project input cannot be None!")

    def _extract_fp_from_config(self, fp_key):
        """Extract the file path from the config dictionary."""
        file_path = self._config.get(fp_key)
        if file_path is not None:
            file_path = file_path.replace("REVIEW_DATA_DIR", REVIEW_DATA_DIR)
            file_path = Path(file_path).expanduser().resolve()
        return file_path

    @property
    def _project_files(self):
        """:obj:`generator`: Generator of project-related files only."""
        for file in self.all_files:
            scenario = strip_rev_filename_endings(file.name)
            if scenario.endswith(".csv"):
                print(scenario)
                continue
            yield scenario, file

    def _safe_read(self, fp_key, default_fp=None):
        """Read the data corresponding to the config key."""
        path = self._extract_fp_from_config(fp_key) or default_fp
        return _safe_read_csv(path)

    def _set_config(self):
        """Set the config, raise error is project not found."""
        for name, config in PROJECT_CONFIGS.items():
            if name.lower() == self.project.lower():
                self._config = config

        if self._config is None:
            raise ValueError(
                f"No project with name {self.project!r} found in config "
                f"directory"
            )


@lru_cache(maxsize=16)
def _safe_read_csv(path):
    """Read the csv from path without throwing error if it DNE."""
    try:
        data = pd.read_csv(path)
    except (ValueError, FileNotFoundError):
        data = None
    return data
