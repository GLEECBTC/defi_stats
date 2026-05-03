#!/bin/bash

set +xu

# Starting DeFi API
clear
cd $(pwd)/api
source .env
echo $HOME
echo $USER
echo $PATH
export PATH="/home/atomic/.local/bin:$PATH"
echo $PATH
poetry env use /usr/bin/python3.10
poetry run uvicorn main:app --host ${API_HOST} --port ${API_PORT}
