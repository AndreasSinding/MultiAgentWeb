#!/usr/bin/env bash
set -e

# Ask Oryx to generate the startup script. This step:
#  - reads /home/site/wwwroot/oryx-manifest.toml
#  - EXTRACTS /home/site/wwwroot/output.tar.gz to /tmp/<hash>
#  - creates /opt/startup/startup.sh that activates the venv and calls our command
oryx create-script \
  -appPath /home/site/wwwroot \
  -output /opt/startup/startup.sh \
  -virtualEnvName antenv \
  -defaultApp /opt/defaultsite \
  -userStartupCommand "gunicorn -k uvicorn.workers.UvicornWorker -w 2 -t 120 -b 0.0.0.0:8000 main:app"

# Now run the script Oryx generated
exec /bin/bash /opt/startup/startup.sh
