# -*- coding: utf-8 -*-
"""Map class.

Used in (at least) the scenario and reeds pages.
"""
import os
import copy


import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from reView.pages.scenario.model import build_name
from reView.pages.scenario.view import MAP_LAYOUT
from reView.utils.classes import DiffUnitOptions
from reView.utils.bespoke import BespokeUnpacker
from reView.utils.config import Config
from reView.utils.constants import AGGREGATIONS, COLORS
from reView.utils.functions import convert_to_title


class Map:
    """Methods for building the mapbox scatter plot."""

    def __init__(
        self,
        df,
        project,
        basemap,
        color,
        point_size,
        reverse_color,
        signal_dict,
        trigger,
        user_ymin=None,
        user_ymax=None,
        map_selection=None,
        click_selection=None,
        demand_data=None,
        title_size=18,
    ):
        """Initialize ScatterPlot object."""
        self.df = df
        self.basemap = basemap
        self.click_selection = click_selection or {}
        self.color = color
        self.map_selection = map_selection
        self.point_size = point_size
        self.project = project
        self.reverse_color = reverse_color
        self.signal_dict = signal_dict
        self.trigger = trigger
        self.title_size = title_size
        self.demand_data = demand_data
        self._y = self.signal_dict["y"]

        config = Config(self.project)
        self.units = config.units.get(self._y, "")
        self._ymin = user_ymin or config.scales.get(self._y, {}).get("min")
        self._ymax = user_ymax or config.scales.get(self._y, {}).get("max")

        # Unpack bespoke turbines if available and a point was clicked
        if "clickData" in self.trigger and "turbine_y_coords" in self.df:
            unpacker = BespokeUnpacker(self.df, self.click_selection)
            self.df = unpacker.unpack_turbines()

        # Store the capacity values up to this point
        self.mapcap = self.df[["sc_point_gid", "print_capacity"]].to_dict()

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
                hover_name="text",
            )
            figure.update_traces(marker=self.marker)
        else:
            # Create data object
            figure = px.scatter_mapbox(
                data_frame=self.df,
                lon="longitude",
                lat="latitude",
                custom_data=["sc_point_gid", "print_capacity"],
                hover_name="text",
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
        if self.demand_data is not None:
            text = (
                self.demand_data["sera_node"]
                + ", "
                + self.demand_data["State"]
                + ". <br>Demand:   "
                + self.demand_data["load"].astype(str)
                + " kg"
            )
        elif self.units == "category":
            try:
                text = (
                    self.df["county"]
                    + " County, "
                    + self.df["state"]
                    + ": <br>   "
                    + self.df[self.y].astype(str)
                    + " "
                    + self.units
                )
            except KeyError:
                text = round(self.df[self.y], 2).astype(str) + " " + self.units
        else:
            extra_str = ""
            if "hydrogen_annual_kg" in self.df:
                extra_str += (
                    "<br>    H2 Supply:    "
                    + self.df["hydrogen_annual_kg"].apply(lambda x: f"{x:,}")
                    + " kg    "
                )
            if "dist_to_selected_load" in self.df:
                extra_str += (
                    "<br>    Dist to load:    "
                    + self.df["dist_to_selected_load"].apply(
                        lambda x: f"{x:,.2f}"
                    )
                    + " km    "
                )

            try:
                text = (
                    self.df["county"]
                    + " County, "
                    + self.df["state"]
                    + ":"
                    + extra_str
                    + f"<br>    {convert_to_title(self.y)}:   "
                    + self.df[self.y].round(2).astype(str)
                    + " "
                    + self.units
                )
            except KeyError:
                text = (
                    extra_str
                    + f"<br>    {convert_to_title(self.y)}:   "
                    + self.df[self.y].round(2).astype(str)
                    + " "
                    + self.units
                )

        return text

    @property
    def layout(self):
        """Build the map data layout dictionary."""
        layout = copy.deepcopy(MAP_LAYOUT)
        layout["mapbox"]["style"] = self.basemap
        layout["showlegend"] = self.show_legend
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
                reversescale=self.reverse_color,
                size=self.point_size,
            )
        else:
            marker = dict(
                color=self.df[self.y],
                colorscale=COLORS[self.color],
                cmax=None if self.ymax is None else float(self.ymax),  # ?
                cmin=None if self.ymin is None else float(self.ymin),
                opacity=1.0,
                reversescale=self.reverse_color,
                size=self.point_size,
                colorbar=dict(
                    title=dict(
                        text=self.units,
                        font=dict(
                            size=15, color="white", family="New Times Roman"
                        ),
                    ),
                    tickfont=dict(color="white", family="New Times Roman"),
                ),
            )

        return marker

    @property
    def plot_title(self):
        """Build title for plot."""
        title = build_title(
            self.df, self.signal_dict, map_selection=self.map_selection
        )
        return title

    @property
    def show_legend(self):
        """Boolean switch to show/hide legend."""
        return self.units == "category"

    @property
    def y(self):
        """Return appropriate y variable name."""
        # Use demand counts if available
        if "demand_connect_count" in self.df:
            return "demand_connect_count"
        return self._y

    @property
    def ymax(self):
        """Return appropriate ymax value."""
        if self._ymin and not self._ymax:
            return self.df[self.y].max()

        return self._ymax

    @property
    def ymin(self):
        """Return appropriate ymax value."""
        if self._ymax and not self._ymin:
            return self.df[self.y].min()

        return self._ymin


def build_title(df, signal_dict, map_selection=None, chart_selection=None):
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

    if map_selection:
        map_selection_print = "Selected point count: {:,}".format(
            len(map_selection["points"])
        )
        title = "  |  ".join([title, map_selection_print])

    if chart_selection:
        chart_selection_print = "Selected point count: {:,}".format(
            len(chart_selection["points"])
        )
        title = "<br>".join([title, chart_selection_print])

    return title


# should do something more rigorous than this
def infer_recalc(title):
    """Quick title fix for recalc least cost paths."""
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
