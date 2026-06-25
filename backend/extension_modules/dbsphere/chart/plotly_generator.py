"""Plotly-based chart generator with automatic chart type selection."""

from enum import Enum
from typing import Any, Dict, List, cast

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    TABLE = "table"
    HISTOGRAM = "histogram"
    GROUPED_BAR = "grouped_bar"
    AUTO = "auto"


class PlotlyChartGenerator:
    """Generate Plotly charts using heuristics based on DataFrame characteristics."""

    def chart_result_to_image(
        self,
        chart_result: Dict[str, Any],
        format: str = "png",
        width: int = 1200,
        height: int = 800,
    ) -> bytes:
        """Convert a chart_result dict (from generate_chart) to image bytes.

        Args:
            chart_result: Dict with keys: data, columns, dtypes, chart_type,
                          numeric_cols, categorical_cols, datetime_cols, title.
            format: Image format (png, jpeg, svg, pdf).
            width: Image width in pixels.
            height: Image height in pixels.

        Returns:
            Image bytes in the requested format.
        """
        # Reconstruct DataFrame from chart_result
        df = pd.DataFrame(chart_result["data"], columns=chart_result["columns"])

        # Restore dtypes
        for col, dtype_str in chart_result.get("dtypes", {}).items():
            if col not in df.columns:
                continue
            try:
                if "int" in dtype_str:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif "float" in dtype_str:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif "datetime" in dtype_str:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            except Exception:
                pass

        chart_type = ChartType(chart_result["chart_type"])
        title = chart_result.get("title", "Chart")
        numeric_cols = chart_result.get("numeric_cols", [])
        categorical_cols = chart_result.get("categorical_cols", [])
        datetime_cols = chart_result.get("datetime_cols", [])

        fig = self._generate_by_explicit_type(
            df, title, chart_type, numeric_cols, categorical_cols, datetime_cols
        )

        return fig.to_image(format=format, width=width, height=height)

    # Theme colors
    THEME_COLORS = {
        "navy": "#023d60",
        "cream": "#e7e1cf",
        "teal": "#15a8a8",
        "orange": "#fe5d26",
        "magenta": "#bf1363",
    }

    # Color palette for charts
    COLOR_PALETTE = px.colors.qualitative.Bold

    def _validate_chart_type(
        self,
        chart_type: ChartType,
        numeric_cols: List[str],
        categorical_cols: List[str],
        datetime_cols: List[str],
        all_columns: List[str],
    ) -> tuple[ChartType | None, str | None]:
        """Validate if requested chart type is compatible with data.

        Returns:
            (chart_type, None) if valid
            (None, error_message) if invalid
        """
        if chart_type == ChartType.TABLE:
            return (chart_type, None)  # Always valid

        if chart_type == ChartType.PIE:
            if len(numeric_cols) >= 1 and len(categorical_cols) >= 1:
                return (chart_type, None)
            return (
                None,
                "Pie chart requires at least 1 categorical column and 1 numeric column",
            )

        if chart_type == ChartType.LINE:
            if len(datetime_cols) > 0 and len(numeric_cols) > 0:
                return (chart_type, None)
            return (None, "Line chart requires datetime column and numeric column")

        if chart_type == ChartType.BAR:
            if len(categorical_cols) >= 1 and len(numeric_cols) >= 1:
                return (chart_type, None)
            return (
                None,
                "Bar chart requires at least 1 categorical column and 1 numeric column",
            )

        if chart_type == ChartType.SCATTER:
            if len(numeric_cols) >= 2:
                return (chart_type, None)
            return (None, "Scatter plot requires at least 2 numeric columns")

        if chart_type == ChartType.HISTOGRAM:
            if len(numeric_cols) >= 1:
                return (chart_type, None)
            return (None, "Histogram requires at least 1 numeric column")

        if chart_type == ChartType.HEATMAP:
            if len(numeric_cols) >= 2:
                return (chart_type, None)
            return (None, "Heatmap requires at least 2 numeric columns")

        if chart_type == ChartType.GROUPED_BAR:
            if len(categorical_cols) >= 2 or (
                len(categorical_cols) >= 1 and len(numeric_cols) >= 2
            ):
                return (chart_type, None)
            return (
                None,
                "Grouped bar chart requires at least 2 categorical columns or 1 categorical + 2 numeric columns",
            )

        # Unknown chart type
        return (None, f"Unknown chart type: {chart_type}")

    def generate_chart(
        self,
        df: pd.DataFrame,
        title: str = "Chart",
        chart_type: ChartType = ChartType.AUTO,
    ) -> Dict[str, Any]:
        """Convert DataFrame to JSON format for frontend rendering.

        Returns DataFrame data with metadata for chart type inference.
        The frontend will handle chart generation using Plotly.js.

        Args:
            df: DataFrame to visualize
            title: Title for the chart
            chart_type: Suggested chart type (can be overridden by frontend)

        Returns:
            Dictionary with DataFrame data and metadata

        Raises:
            ValueError: If DataFrame is empty
        """
        if df.empty:
            raise ValueError("Cannot visualize empty DataFrame")

        # Coerce numeric-like object columns
        df_work = df.copy()
        for col in df_work.columns:
            if df_work[col].dtype == object:
                series = pd.to_numeric(df_work[col], errors="coerce")
                if series.notna().mean() >= 0.8:
                    df_work[col] = series

        # Analyze column types
        numeric_cols = df_work.select_dtypes(include=["number"]).columns.tolist()
        categorical_cols = df_work.select_dtypes(
            include=["object", "category"]
        ).columns.tolist()

        def _detect_datetime_like_columns(df):
            candidates = []
            for col in df.columns:
                if df[col].dtype == object:
                    try:
                        pd.to_datetime(df[col])
                        candidates.append(col)
                    except Exception:
                        pass
            return candidates

        datetime_cols = df.select_dtypes(
            include=["datetime64"]
        ).columns.tolist() + _detect_datetime_like_columns(df)

        # Infer chart type using heuristics with validation
        inferred_type = None
        is_timeseries = len(datetime_cols) > 0
        explicit_error = None

        # If user explicitly requested a chart type, validate it first
        if chart_type != ChartType.AUTO:
            validated_type, error = self._validate_chart_type(
                chart_type, numeric_cols, categorical_cols, datetime_cols, df.columns
            )
            if validated_type:
                inferred_type = validated_type
            else:
                explicit_error = error
                # Fall back to auto-selection
                chart_type = ChartType.AUTO

        # Auto-select chart type based on data characteristics
        if chart_type == ChartType.AUTO:
            if len(df.columns) >= 4:
                inferred_type = ChartType.TABLE
            elif is_timeseries and len(numeric_cols) > 0:
                inferred_type = ChartType.LINE
            elif len(numeric_cols) == 1 and len(categorical_cols) == 0:
                inferred_type = ChartType.HISTOGRAM
            elif len(numeric_cols) == 1 and len(categorical_cols) == 1:
                inferred_type = ChartType.BAR
            elif len(categorical_cols) >= 1 and len(numeric_cols) >= 2:
                inferred_type = ChartType.GROUPED_BAR
            elif len(numeric_cols) == 2:
                inferred_type = ChartType.SCATTER
            elif len(numeric_cols) >= 3:
                inferred_type = ChartType.HEATMAP
            elif len(categorical_cols) >= 2:
                inferred_type = ChartType.GROUPED_BAR
            else:
                inferred_type = ChartType.BAR

        # Convert DataFrame to JSON-serializable format
        # Handle datetime columns
        df_json = df_work.copy()
        for col in datetime_cols:
            if col in df_json.columns:
                df_json[col] = df_json[col].astype(str)

        # NaN → None (json.dumps에서 null로 직렬화)
        # float64 컬럼은 None 을 담을 수 없어 where(notna, None) 만으로는 NaN 이
        # 다시 NaN 으로 강제된다 → astype(object) 로 먼저 바꿔야 None 이 유지되어
        # json.dumps 가 null(유효 JSON)로 직렬화한다. (0 매출 → 이익률 NaN 등)
        df_json = df_json.astype(object).where(df_json.notna(), None)

        # Return DataFrame as JSON with metadata
        status = "auto_success" if explicit_error is None else "fallback_auto"

        return {
            "chart_result": {
                "columns": df_json.columns.tolist(),
                "data": df_json.to_dict("records"),
                "dtypes": {col: str(dtype) for col, dtype in df_json.dtypes.items()},
                "numeric_cols": numeric_cols,
                "categorical_cols": categorical_cols,
                "datetime_cols": datetime_cols,
                "chart_type": inferred_type.value,
                "title": title,
            },
            "status": status,
            "requested_chart_type": chart_type.value,
            "used_chart_type": inferred_type.value,
            "error_reason": explicit_error,
        }

    def _generate_by_explicit_type(
        self,
        df: pd.DataFrame,
        title: str,
        chart_type: ChartType,
        numeric_cols: List[str],
        categorical_cols: List[str],
        datetime_cols: List[str],
    ) -> go.Figure:
        if chart_type == ChartType.TABLE:
            return self._create_table(df, title)

        if chart_type == ChartType.PIE:
            if len(numeric_cols) >= 1 and len(categorical_cols) >= 1:
                return self._create_pie_chart(
                    df, categorical_cols[0], numeric_cols[0], title
                )
            raise ValueError("Pie chart requires 1 categorical and 1 numeric column")

        if chart_type == ChartType.LINE:
            if datetime_cols and numeric_cols:
                return self._create_time_series_chart(
                    df, datetime_cols[0], numeric_cols, title
                )
            raise ValueError("Line chart requires datetime + numeric columns")

        if chart_type == ChartType.BAR:
            if categorical_cols and numeric_cols:
                return self._create_bar_chart(
                    df, categorical_cols[0], numeric_cols[0], title
                )
            raise ValueError("Bar chart requires categorical + numeric columns")

        if chart_type == ChartType.SCATTER:
            if len(numeric_cols) >= 2:
                return self._create_scatter_plot(
                    df, numeric_cols[0], numeric_cols[1], title
                )
            raise ValueError("Scatter plot requires at least 2 numeric columns")

        if chart_type == ChartType.HISTOGRAM:
            if len(numeric_cols) >= 1:
                return self._create_histogram(df, numeric_cols[0], title)
            raise ValueError("Histogram requires at least 1 numeric column")

        if chart_type == ChartType.HEATMAP:
            if len(numeric_cols) >= 2:
                return self._create_correlation_heatmap(df, numeric_cols, title)
            raise ValueError("Heatmap requires numeric columns")

        if chart_type == ChartType.GROUPED_BAR:
            # Prefer value-based grouped bars when numeric + 2 categorical
            if len(categorical_cols) >= 2 and len(numeric_cols) >= 1:
                return self._create_grouped_bar_value_chart(
                    df, categorical_cols[:2], numeric_cols[0], title
                )
            if len(categorical_cols) >= 2:
                return self._create_grouped_bar_chart(df, categorical_cols[:2], title)
            raise ValueError("Grouped bar requires at least 2 categorical columns")

        raise ValueError(f"Unsupported chart type: {chart_type}")

    def _apply_standard_layout(self, fig: go.Figure) -> go.Figure:
        """Apply consistent styling to all charts."""
        fig.update_layout(
            paper_bgcolor="white",
            plot_bgcolor="white",
            font={"color": self.THEME_COLORS["navy"]},
            autosize=True,
            colorway=self.COLOR_PALETTE,
            margin=dict(l=40, r=20, t=50, b=40),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
        )
        fig.update_xaxes(showgrid=True, gridcolor="#e5e7eb", zerolinecolor="#e5e7eb")
        fig.update_yaxes(showgrid=True, gridcolor="#e5e7eb", zerolinecolor="#e5e7eb")
        return fig

    def _create_pie_chart(
        self, df: pd.DataFrame, cat_col: str, val_col: str, title: str
    ) -> go.Figure:
        agg_df = df.groupby(cat_col)[val_col].sum().reset_index()

        fig = px.pie(
            agg_df,
            names=cat_col,
            values=val_col,
            title=title,
            color_discrete_sequence=self.COLOR_PALETTE,
        )
        self._apply_standard_layout(fig)
        return fig

    def _create_histogram(self, df: pd.DataFrame, column: str, title: str) -> go.Figure:
        """Create a histogram for a single numeric column."""
        fig = px.histogram(
            df,
            x=column,
            title=title,
            color_discrete_sequence=[self.THEME_COLORS["teal"]],
        )
        fig.update_layout(xaxis_title=column, yaxis_title="Count", showlegend=False)
        self._apply_standard_layout(fig)
        return fig

    def _create_bar_chart(
        self, df: pd.DataFrame, x_col: str, y_col: str, title: str
    ) -> go.Figure:
        """Create a bar chart for categorical vs numeric data."""
        agg_df = df.groupby(x_col)[y_col].sum().reset_index()
        fig = px.bar(
            agg_df,
            x=x_col,
            y=y_col,
            title=title,
            color_discrete_sequence=[self.THEME_COLORS["orange"]],
        )
        fig.update_layout(xaxis_title=x_col, yaxis_title=y_col)
        self._apply_standard_layout(fig)
        return fig

    def _create_scatter_plot(
        self, df: pd.DataFrame, x_col: str, y_col: str, title: str
    ) -> go.Figure:
        """Create a scatter plot for two numeric columns."""
        label_cols = [
            c for c in df.columns if c not in (x_col, y_col) and df[c].dtype == object
        ]
        label_col = label_cols[0] if label_cols else None

        size_series = df[x_col].fillna(0) + df[y_col].fillna(0)
        size_series = size_series.replace(0, 1)

        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            title=title,
            color_discrete_sequence=[self.THEME_COLORS["magenta"]],
            size=size_series,
            size_max=24,
            hover_name=label_col,
            text=label_col if label_col and len(df) <= 15 else None,
        )
        fig.update_traces(
            marker=dict(opacity=0.85, line=dict(width=0.6, color="#1f2937")),
            textposition="top center",
            textfont=dict(size=10),
        )
        fig.update_layout(xaxis_title=x_col, yaxis_title=y_col)

        # Add a y=x reference line when ranges are comparable
        try:
            min_val = float(min(df[x_col].min(), df[y_col].min()))
            max_val = float(max(df[x_col].max(), df[y_col].max()))
            fig.add_shape(
                type="line",
                x0=min_val,
                y0=min_val,
                x1=max_val,
                y1=max_val,
                line=dict(color="#9ca3af", width=1, dash="dash"),
            )
        except Exception:
            pass

        self._apply_standard_layout(fig)
        return fig

    def _create_correlation_heatmap(
        self, df: pd.DataFrame, columns: List[str], title: str
    ) -> go.Figure:
        """Create a correlation heatmap for multiple numeric columns."""
        corr_matrix = df[columns].corr()
        colorscale = [
            [0.0, self.THEME_COLORS["navy"]],
            [0.5, self.THEME_COLORS["cream"]],
            [1.0, self.THEME_COLORS["teal"]],
        ]
        fig = cast(
            go.Figure,
            px.imshow(
                corr_matrix,
                title=title,
                labels=dict(color="Correlation"),
                x=columns,
                y=columns,
                color_continuous_scale=colorscale,
                zmin=-1,
                zmax=1,
            ),
        )
        self._apply_standard_layout(fig)
        return fig

    def _create_time_series_chart(
        self, df: pd.DataFrame, time_col: str, value_cols: List[str], title: str
    ) -> go.Figure:
        """Create a time series line chart."""
        fig = go.Figure()

        for i, col in enumerate(value_cols[:5]):  # Limit to 5 lines for readability
            color = self.COLOR_PALETTE[i % len(self.COLOR_PALETTE)]
            LINE_STYLES = ["solid", "dash", "dot", "dashdot"]

            fig.add_trace(
                go.Scatter(
                    x=df[time_col],
                    y=df[col],
                    mode="lines+markers",
                    name=col,
                    line=dict(
                        color=color,
                        width=2,
                        dash=LINE_STYLES[i % len(LINE_STYLES)],
                    ),
                    marker=dict(size=5),
                )
            )

        fig.update_layout(
            title=title,
            xaxis_title=time_col,
            yaxis_title="Value",
            hovermode="x unified",
        )
        self._apply_standard_layout(fig)
        return fig

    def _create_multi_series_bar_chart(
        self, df: pd.DataFrame, cat_col: str, value_cols: List[str], title: str
    ) -> go.Figure:
        """Create a grouped bar chart comparing multiple numeric series."""
        long_df = df.melt(
            id_vars=[cat_col],
            value_vars=value_cols,
            var_name="series",
            value_name="value",
        )
        fig = px.bar(
            long_df,
            x=cat_col,
            y="value",
            color="series",
            title=title,
            barmode="group",
            color_discrete_sequence=self.COLOR_PALETTE,
        )
        fig.update_layout(xaxis_title=cat_col, yaxis_title="Value")
        self._apply_standard_layout(fig)
        return fig

    def _create_grouped_bar_chart(
        self, df: pd.DataFrame, categorical_cols: List[str], title: str
    ) -> go.Figure:
        """Create a grouped bar chart for multiple categorical columns."""
        if len(categorical_cols) >= 2:
            grouped = df.groupby(categorical_cols[:2]).size().reset_index(name="count")
            fig = px.bar(
                grouped,
                x=categorical_cols[0],
                y="count",
                color=categorical_cols[1],
                title=title,
                barmode="group",
                color_discrete_sequence=self.COLOR_PALETTE,
            )
            self._apply_standard_layout(fig)
            return fig
        else:
            counts = df[categorical_cols[0]].value_counts().reset_index()
            counts.columns = [categorical_cols[0], "count"]
            fig = px.bar(
                counts,
                x=categorical_cols[0],
                y="count",
                title=title,
                color_discrete_sequence=[self.THEME_COLORS["teal"]],
            )
            self._apply_standard_layout(fig)
            return fig

    def _create_grouped_bar_value_chart(
        self, df: pd.DataFrame, categorical_cols: List[str], value_col: str, title: str
    ) -> go.Figure:
        """Create a grouped bar chart using a numeric value column."""
        group_cols = categorical_cols[:2]
        agg_df = df.groupby(group_cols)[value_col].sum().reset_index()
        fig = px.bar(
            agg_df,
            x=group_cols[0],
            y=value_col,
            color=group_cols[1],
            title=title,
            barmode="group",
            color_discrete_sequence=self.COLOR_PALETTE,
        )
        fig.update_layout(xaxis_title=group_cols[0], yaxis_title=value_col)
        self._apply_standard_layout(fig)
        return fig

    def _create_generic_chart(
        self, df: pd.DataFrame, col1: str, col2: str, title: str
    ) -> go.Figure:
        """Create a generic chart for any two columns."""
        if pd.api.types.is_numeric_dtype(df[col1]) and pd.api.types.is_numeric_dtype(
            df[col2]
        ):
            return self._create_scatter_plot(df, col1, col2, title)
        else:
            fig = px.bar(
                df,
                x=col1,
                y=col2,
                title=title,
                color_discrete_sequence=[self.THEME_COLORS["orange"]],
            )
            self._apply_standard_layout(fig)
            return fig

    def _create_table(self, df: pd.DataFrame, title: str) -> go.Figure:
        """Create a Plotly table for DataFrames with 4 or more columns."""
        header_values = list(df.columns)
        cell_values = [df[col].tolist() for col in df.columns]

        fig = go.Figure(
            data=[
                go.Table(
                    header=dict(
                        values=header_values,
                        fill_color=self.THEME_COLORS["navy"],
                        font=dict(color="white", size=12),
                        align="left",
                    ),
                    cells=dict(
                        values=cell_values,
                        fill_color=[
                            [
                                self.THEME_COLORS["cream"] if i % 2 == 0 else "white"
                                for i in range(len(df))
                            ]
                        ],
                        font=dict(color=self.THEME_COLORS["navy"], size=11),
                        align="left",
                    ),
                )
            ]
        )

        fig.update_layout(title=title, font={"color": self.THEME_COLORS["navy"]})

        return fig
