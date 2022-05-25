# -*- coding: utf-8 -*-
"""Element builders.

Methods for building html and core component elements given user inputs in
scenario_callbacks.

Created on Fri May 20 12:07:29 2022

@author: twillia2
"""
import copy
import json
import os

import nltk
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from reView.pages.scenario.scenario import MAP_LAYOUT
from reView.pages.scenario.scenario_data import (
    apply_all_selections,
    build_name,
    cache_map_data,
)
from reView.utils.bespoke import BespokeUnpacker
from reView.utils.classes import DiffUnitOptions
from reView.utils.config import Config
from reView.utils.constants import COLORS
from reView.utils.constants import AGGREGATIONS
from reView.utils.functions import convert_to_title


nltk.download("words")
WORDS = nltk.corpus.words.words()  # Download up-to-date version in package data


def infer_recalc(title):
    """Quick title fix for recalc least cost paths."""  # <-------------------- Do better
    variables = ["fcr", "capex", "opex", "losses"]
    if "least" in title.lower():
        title = " ".join(title.split(" ")[:-1])
        if any([v in title for v in variables]):
            title = title.replace("-", ".")
            first_part = title.split("  ")[0]
            recalc_part = title.split("  ")[1]
            new_part = []
            for part in recalc_part.split():
                letters = "".join([c for c in part if c.isalpha()])
                numbers = part.replace(letters, "")
                new_part.append(letters + ": " + numbers)
            title = first_part + " (" + ", ".join(new_part) + ")"
    return title


def build_title(df, signal_dict, mapsel=None, chartsel=None):
    """Create chart title."""
    # Unpack signal
    path = signal_dict["path"]
    path2 = signal_dict["path2"]

    # Project configuration object
    config = Config(signal_dict["project"])

    recalc = signal_dict["recalc"]
    y = signal_dict["y"]
    y_no_diff_suffix = DiffUnitOptions.remove_from_variable_name(y)
    diff = DiffUnitOptions.from_variable_name(y) is not None
    is_percentage_diff = (
        DiffUnitOptions.from_variable_name(y) == DiffUnitOptions.PERCENTAGE
    )
    if diff and is_percentage_diff:
        units = "%"
    else:
        units = config.units.get(y_no_diff_suffix, "")

    if recalc == "off":
        recalc_table = None
    else:
        recalc_table = signal_dict["recalc_table"]

    # Infer scenario name from path
    s1 = build_name(path)

    # User specified FCR?
    if recalc_table and "least" not in s1.lower():
        msgs = []
        for k, v in recalc_table["scenario_a"].items():
            if v:
                msgs.append(f"{k}: {v}")
        if msgs:
            reprint = ", ".join(msgs)
            s1 += f" ({reprint})"

    # Least Cost
    if "least" in s1.lower():
        s1 = infer_recalc(s1)

    # Append variable title
    title = "<br>".join(
        [s1, config.titles.get(y_no_diff_suffix, convert_to_title(y))]
    )

    # Add variable aggregation value
    if y_no_diff_suffix in AGGREGATIONS:
        ag_fun = AGGREGATIONS[y_no_diff_suffix]
        if ag_fun == "mean":
            conditioner = "Average"
        else:
            conditioner = "Total"
    else:
        ag_fun = "mean"
        conditioner = "Average"
        # ag_fun = "sum"
        # conditioner = "Sum"

    # Difference title
    if diff:
        s2 = os.path.basename(path2).replace("_sc.csv", "")
        s2 = " ".join([s.capitalize() for s in s2.split("_")])
        if recalc_table:
            msgs = []
            for k, v in recalc_table["scenario_b"].items():
                if v:
                    msgs.append(f"{k}: {v}")
            if msgs:
                reprint = ", ".join(msgs)
                s2 += f" ({reprint})"

        title = "{} vs. <br>{}<br>".format(s1, s2) + config.titles.get(
            y_no_diff_suffix, convert_to_title(y)
        )
        conditioner = f"{units} Difference | Average"
        punits = ""

    is_df = isinstance(df, pd.core.frame.DataFrame)
    y_exists = y_no_diff_suffix and y_no_diff_suffix.lower() != "none"
    not_category = units != "category"

    # Map title (not chart)
    if is_df and y_exists and not_category:
        if y_no_diff_suffix == "capacity" and units != "%":
            ag = round(df[y].apply(ag_fun) / 1_000_000, 4)
            punits = ["TW"]
            conditioner = conditioner.replace("Average", "Total")
        else:
            ag = round(df[y].apply(ag_fun), 2)

            if diff:
                punits = []
            else:
                punits = [config.units.get(y_no_diff_suffix, "")]
        ag_print = ["  |  {}: {:,}".format(conditioner, ag)]
        title = " ".join([title] + ag_print + punits)
        if "hydrogen_annual_kg" in df:
            ag = round(df["hydrogen_annual_kg"].sum(), 2)
            ag_print = ["  |  {}: {:,}".format("Total H2", ag)]
            title = " ".join([title] + ag_print)

    if mapsel:
        mapsel_print = "Selected point count: {:,}".format(
            len(mapsel["points"])
        )
        title = "  |  ".join([title, mapsel_print])

    if chartsel:
        chartsel_print = "Selected point count: {:,}".format(
            len(chartsel["points"])
        )
        title = "<br>".join([title, chartsel_print])

    return title


class Map:
    """Methods for building the mapbox scatter plot."""

    def __init__(self, basemap, chartsel, clicksel, color, mapfunc, mapsel,
                 point_size, project, rev_color, signal, trigger, uymin, uymax,
                 title_size=18):
        """Initialize ScatterPlot object."""
        self.basemap = basemap
        self.chartsel = chartsel
        self.clicksel = clicksel
        self.color = color
        self.mapfunc = mapfunc
        self.mapsel = mapsel
        self.point_size = point_size
        self.project = project
        self.rev_color = rev_color
        self.signal = signal
        self.trigger = trigger
        self.title_size = title_size
        self.uymax = uymax 
        self.uymin = uymin
        self.unpack()

    def __repr__(self):
        """Return representation string."""
        name = self.__class__.__name__
        params = [f"{k}={v}" for k, v in self.__dict__.items() if k != "df"]
        params.append(f"df='dataframe with {self.df.shape[0]:,} rows'")
        param_str = ", ".join(params)
        msg = f"<{name} object: {param_str}>"
        return msg

    @property
    def figure(self):
        """Build scatter plot figure."""
        self.df["text"] = self.hover_text
        if self.df.empty:
            figure = go.Figure()
            figure.update_layout(
                xaxis={"visible": False},
                yaxis={"visible": False},
                annotations=[
                    {
                        "text": "No matching data found",
                        "xref": "paper",
                        "yref": "paper",
                        "showarrow": False,
                        "font": {"size": 28},
                    }
                ],
            )
        elif self.units == "category":
            # Create data object
            figure = px.scatter_mapbox(
                data_frame=self.df,
                color=self.y,
                lon="longitude",
                lat="latitude",
                custom_data=["sc_point_gid", "print_capacity"],
                hover_name="text"
            )
            figure.update_traces(marker=self.marker)
        else:
            # Create data object
            figure = px.scatter_mapbox(
                data_frame=self.df,
                lon="longitude",
                lat="latitude",
                custom_data=["sc_point_gid", "print_capacity"],
                hover_name="text"
            )
            figure.update_traces(marker=self.marker)

            if self.demand_data is not None:
                self.demand_data["text"] = (
                    self.demand_data["sera_node"]
                    + ", "
                    + self.demand_data["State"]
                    + ". <br>Demand:   "
                    + self.demand_data["load"].astype(str)
                    + " kg"
                )

                fig2 = px.scatter_mapbox(
                    self.demand_data,
                    lon="longitude",
                    lat="latitude",
                    color_discrete_sequence=["red"],
                    hover_name="text",
                )
                figure.add_trace(fig2.data[0])

        # Update the layout
        layout = self.layout
        figure.update_layout(**layout)

        return figure

    @property
    def hover_text(self):
        """Return hover text column."""
        units = self.units
        df = self.df
        y = self.y
        if self.demand_data is not None:
            text = (
                self.demand_data["sera_node"]
                + ", "
                + self.demand_data["State"]
                + ". <br>Demand:   "
                + self.demand_data["load"].astype(str)
                + " kg"
            )
        elif units == "category":
            try:
                text = (
                    df["county"]
                    + " County, "
                    + df["state"]
                    + ": <br>   "
                    + df[y].astype(str)
                    + " "
                    + units
                )
            except:
                text = round(df[y], 2).astype(str) + " " + units
        else:
            extra_str = ""
            if "hydrogen_annual_kg" in df:
                extra_str += (
                    "<br>    H2 Supply:    "
                    + df["hydrogen_annual_kg"].apply(lambda x: f"{x:,}")
                    + " kg    "
                )
            if "dist_to_selected_load" in df:
                extra_str += (
                    "<br>    Dist to load:    "
                    + df["dist_to_selected_load"].apply(lambda x: f"{x:,.2f}")
                    + " km    "
                )
    
            try:
                text = (
                    df["county"]
                    + " County, "
                    + df["state"]
                    + ":"
                    + extra_str
                    + f"<br>    {self.to_human(y)}:   "
                    + df[y].round(2).astype(str)
                    + " " + units
                )
            except:
                text = (
                  extra_str
                  + f"<br>    {self.to_human(y)}:   "
                  + df[y].round(2).astype(str)
                  + " " + units
                )

        return text

    @property
    def layout(self):
        """Build the map data layout dictionary."""
        layout = copy.deepcopy(MAP_LAYOUT)
        layout["mapbox"]["style"] = self.basemap
        layout["showlegend"] = self.showlegend
        layout["title"]["text"] = self.plot_title
        layout["uirevision"] = True
        layout["yaxis"] = dict(range=[self.ymin, self.ymax])
        layout["legend"] = dict(
            title_font_family="Times New Roman",
            bgcolor="#E4ECF6",
            font=dict(family="Times New Roman", size=15, color="black"),
        )
        return layout

    @property
    def marker(self):
        """Return marker dictionary."""
        if self.units == "category":
            marker = dict(
                opacity=1.0,
                reversescale=self.rev_color,
                size=self.point_size,
            )
        else:
            pcolor = COLORS[self.color]
            marker = dict(
                color=self.df[self.y],
                colorscale=pcolor,
                cmax=None if self.ymax is None else float(self.ymax),  # ?
                cmin=None if self.ymin is None else float(self.ymin),
                opacity=1.0,
                reversescale=self.rev_color,
                size=self.point_size,
                colorbar=dict(
                    title=dict(
                        text=self.units,
                        font=dict(
                            size=15,
                            color="white",
                            family="New Times Roman"
                        ),
                    ),
                    tickfont=dict(
                        color="white",
                        family="New Times Roman"
                    ),
                ),
            )

        return marker

    @property
    def plot_title(self):
        """Build title for plot."""
        title = build_title(self.df, self.signal_dict, mapsel=self.mapsel)
        return title

    @property
    def showlegend(self):
        """Boolean switch to show/hide legend."""
        if self.units == "category":
            show = True
        else:
            show = False
        return show

    def to_human(self, string):
        """Convert string to human readable format."""
        parts = []
        if string is not None:
            for part in string.split("_"):
                if part not in WORDS:
                    part = part.upper()
                else:
                    part = part.title()
                parts.append(part)
        hstring = " ".join(parts)
        return hstring

    def unpack(self):
        """Unpack signal and set values."""
        # Unpack signal and derive elements
        self.signal_dict = json.loads(self.signal)
        self.df = cache_map_data(self.signal_dict)
        self.df.index = self.df["index"]
        self.x = self.signal_dict["x"]
        self._y = self.signal_dict["y"]
        self.config = Config(self.project)
        self.units = self.config.units.get(self._y, "")
        scale = self.config.scales.get(self._y, {})
        self._ymin = scale.get("min")
        self._ymax = scale.get("max")

        # Reverse color
        if self.rev_color % 2 == 1:
            self.rev_color = True
        else:
            self.rev_color = False

        # Use user defined value ranges
        if self.uymin:
            self._ymin = self.uymin
        if self.uymax:
            self._ymax = self.uymax

        # Apply all farm level filters
        self.df, self.demand_data = apply_all_selections(
            self.df,
            self.mapfunc,
            self.project,
            self.chartsel,
            self.mapsel,
            self.clicksel
        )

        # Unpack bespoke turbines if available and a point was clicked
        if "clickData" in self.trigger and "turbine_y_coords" in self.df:
            unpacker = BespokeUnpacker(self.df, self.clicksel)
            self.df = unpacker.unpack_turbines()

        # Store the capacity values up to this point
        self.mapcap = self.df[["sc_point_gid", "print_capacity"]].to_dict()

    @property
    def y(self):
        """Return appropriate y variable name."""
        # Use demand counts if available
        if "demand_connect_count" in self.df:
            y = "demand_connect_count"
        else:
            y = self._y
        return y

    @property
    def ymax(self):
        """Return appropriate ymax value."""
        if self._ymin and not self._ymax:
            ymax = self.df[self.y].max()
        else:
            ymax = self._ymax
        return ymax

    @property
    def ymin(self):
        """Return appropriate ymax value."""
        if self._ymax and not self._ymin:
            ymin = self.df[self.y].min()
        else:
            ymin = self._ymin
        return ymin
