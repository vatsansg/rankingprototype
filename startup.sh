#!/bin/bash
# Azure App Service (Linux, Python) "Startup Command" for this app. Runs on every cold start
# from /home/site/wwwroot -- the built-in Python runtime image does not ship the ODBC Driver
# 18 for SQL Server pyodbc needs, and nothing installed at runtime persists across restarts on
# code-based (Oryx) deploys, so this installs it fresh each time before launching gunicorn.
#
# Uses Microsoft's current official Debian install method (packages-microsoft-prod.deb, which
# registers the repo + signing key together) -- NOT the older manual apt-key/sources.list
# recipe, which relies on the now-deprecated `apt-key` command and can fail on newer images.
# See https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server
#
# All output also goes to /home/LogFiles/startup_debug.log -- /home is the persistent volume
# Kudu exposes, so this survives container restarts and is fetchable even if a crash happens
# before Azure's own container-stream log capture catches up.
set -x
mkdir -p /home/LogFiles
exec > >(tee -a /home/LogFiles/startup_debug.log) 2>&1
echo "=== startup.sh run at $(date -u +%FT%TZ) ==="

if ! dpkg -s msodbcsql18 >/dev/null 2>&1; then
    echo "msodbcsql18 not installed -- installing"
    . /etc/os-release
    DEBIAN_MAJOR=$(echo "${VERSION_ID}" | cut -d '.' -f 1)
    cd /tmp || exit 1
    curl -sSL -O "https://packages.microsoft.com/config/debian/${DEBIAN_MAJOR}/packages-microsoft-prod.deb"
    dpkg -i packages-microsoft-prod.deb
    rm -f packages-microsoft-prod.deb
    apt-get update
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev
    cd /home/site/wwwroot || exit 1
else
    echo "msodbcsql18 already installed, skipping"
fi

echo "=== launching gunicorn ==="
exec gunicorn --bind=0.0.0.0 --timeout 600 wsgi:app
