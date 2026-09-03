#!/bin/bash
# Azure App Service (Linux, Python) "Startup Command" for this app. Runs on every cold start
# from /home/site/wwwroot -- the built-in Python runtime image does not ship the ODBC Driver
# 18 for SQL Server pyodbc needs, and nothing installed at runtime persists across restarts on
# code-based (Oryx) deployments, so this installs it fresh each time before launching gunicorn.
#
# OS version is detected from /etc/os-release rather than hardcoded, so this keeps working if
# Azure's underlying base image moves to a newer Debian release.
set -e

if ! dpkg -s msodbcsql18 >/dev/null 2>&1; then
    . /etc/os-release
    curl -sSL -O https://packages.microsoft.com/keys/microsoft.asc
    apt-key add microsoft.asc >/dev/null 2>&1 || true
    curl -sSL "https://packages.microsoft.com/config/debian/${VERSION_ID}/prod.list" \
        > /etc/apt/sources.list.d/mssql-release.list
    apt-get update -qq
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev -qq
fi

exec gunicorn --bind=0.0.0.0 --timeout 600 wsgi:app
