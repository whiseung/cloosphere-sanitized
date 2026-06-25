from vanna.core.system_prompt.default import DefaultSystemPromptBuilder


class DBSpherePromptBuilder(DefaultSystemPromptBuilder):
    async def build_system_prompt(self, user, tools):
        base = await super().build_system_prompt(user, tools)

        query_generation_block = """
                ============================================================
                Visualization-Aware SQL Generation Strategy
                ============================================================

                When the user's request is intended to be visualized using the visualize_data tool,
                SQL queries MUST be generated not merely to "retrieve data",
                but to produce a **data structure that is easy and natural to visualize**.

                This applies especially when the user:
                - Explicitly or implicitly requests a chart or graph
                - Asks for trends, comparisons, distributions, ratios, compositions, or changes over time

                In such cases, you MUST follow these principles:

                1. First, determine the most appropriate chart type in your reasoning
                (e.g., bar, line, pie, grouped bar, etc.).
                2. Design the SQL query based on the data structure required for that chart
                (axes, grouping dimensions, and values).
                3. Remove unnecessary columns, nested calculations, or raw fields at the SQL stage.
                4. The visualize_data tool is responsible ONLY for rendering.
                All aggregation, grouping, sorting, and shaping of data must be handled by run_sql.

                Warnings:
                - Do NOT pass raw or unstructured SQL results directly into visualize_data.
                - Do NOT force complex analytical requests into a single SQL query.

        """

        return base + "\n\n" + query_generation_block
