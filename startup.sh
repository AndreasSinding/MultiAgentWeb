

#!/usr/bin/env bash 
set -euo pipefail

# Azure provides $PORT; default to 8000 for local runs
PORT="${PORT:-8000}"

# Ask Oryx to generate an app startup script into /opt/startup/startup.sh
# - It will unpack your build into /tmp/<hash>, activate the antenv, and run our command.
oryx create-script \
  -appPath /home/site/wwwroot \
  -output /opt/startup/startup.sh \
  -virtualEnvName antenv \
  -defaultApp /opt/defaultsite \
  -userStartupCommand "gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT} --timeout 600 --workers 1"

# Now execute the script Oryx generated
exec /bin/bash /opt/startup/startup.sh
