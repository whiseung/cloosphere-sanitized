FROM quay.io/jupyter/scipy-notebook:latest

# ── Core: data analysis & visualization ──
RUN pip install --no-cache-dir \
    plotly \
    tabulate \
    openpyxl \
    xlrd \
    python-dateutil \
    sqlalchemy \
    pyarrow \
    fastparquet \
    missingno \
    fuzzywuzzy \
    python-Levenshtein

# ── Optional: may fail on some platforms ──
RUN pip install --no-cache-dir prophet || true

# Default token (override with JUPYTER_TOKEN env var)
ENV JUPYTER_TOKEN=changeme

EXPOSE 8888
