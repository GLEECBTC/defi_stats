#!/bin/bash

echo "Installing apt deps..."
sudo apt update
sudo apt install postgresql postgresql-contrib build-essential python3-dev python3-psycopg2 libpq-dev libmysqlclient-dev default-libmysqlclient-dev pkg-config python-dev-is-python3 libffi-dev

echo "Setup Python 3.10..."
sudo apt update && sudo apt upgrade -y
sudo apt install software-properties-common python3-apt jq -y
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.10 python3.10-distutils python3.10-venv python3.10-dev -y
curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10

echo "Getting coins..."
wget https://raw.githubusercontent.com/GLEECBTC/coins/master/coins
cp coins $(pwd)/mm2/coins
cp coins $(pwd)/mm2_8762/coins
cp coins $(pwd)/mm2_6133/coins
echo "Bootstrapping API coin cache..."
$(pwd)/scripts/bootstrap_coins_cache.sh --force

echo "Setup mm2..."
rpc_password="$(openssl rand -hex 20)-E"
passphrase=$(openssl rand -hex 128)
contents=$(jq '.rpc_password = "'${rpc_password}'"' $(pwd)/mm2_8762/MM2.template.json) && echo -E "${contents}" > $(pwd)/mm2_8762/MM2.json
contents=$(jq '.passphrase = "'${passphrase}'"' $(pwd)/mm2_8762/MM2.json) && echo -E "${contents}" > $(pwd)/mm2_8762/MM2.json

rpc_password="$(openssl rand -hex 20)-E"
passphrase=$(openssl rand -hex 128)
contents=$(jq '.rpc_password = "'${rpc_password}'"' $(pwd)/mm2/MM2.template.json) && echo -E "${contents}" > $(pwd)/mm2/MM2.json
contents=$(jq '.passphrase = "'$passphrase'"' $(pwd)/mm2/MM2.json) && echo -E "${contents}" > $(pwd)/mm2/MM2.json

echo "Setting up .env [netid 7777] file..."
USER_ID=$(id -u)
GROUP_ID=$(id -g)
userpass=$(cat mm2/MM2.json | jq -r '.rpc_password')

echo "USER_ID=${USER_ID}" > .env
echo "GROUP_ID=${GROUP_ID}" >> mm2/.env

echo "MM_CONF_PATH=/home/komodian/mm2/MM2.json" > mm2/.env
echo "MM_COINS_PATH=/home/komodian/mm2/coins" >> mm2/.env
echo "MM_LOG=/home/komodian/mm2/mm2.log" >> mm2/.env
echo "USERPASS=${userpass}" >> mm2/.env
echo "USER_ID=${USER_ID}" >> mm2/.env
echo "GROUP_ID=${GROUP_ID}" >> mm2/.env

echo "Setting up .env [netid 8762] file..."
USER_ID=$(id -u)
GROUP_ID=$(id -g)
userpass=$(cat mm2_8762/MM2.json | jq -r '.rpc_password')

echo "MM_CONF_PATH=/home/komodian/mm2/MM2.json" > mm2_8762/.env
echo "MM_COINS_PATH=/home/komodian/mm2/coins" >> mm2_8762/.env
echo "MM_LOG=/home/komodian/mm2/mm2.log" >> mm2_8762/.env
echo "USERPASS=${userpass}" >> mm2_8762/.env
echo "USER_ID=${USER_ID}" >> mm2_8762/.env
echo "GROUP_ID=${GROUP_ID}" >> mm2_8762/.env

echo "Setting up .env [netid 6133] file..."
rpc_password="$(openssl rand -hex 20)-E"
passphrase=$(openssl rand -hex 128)
contents=$(jq '.rpc_password = "'${rpc_password}'"' $(pwd)/mm2_6133/MM2.template.json) && echo -E "${contents}" > $(pwd)/mm2_6133/MM2.json
contents=$(jq '.passphrase = "'${passphrase}'"' $(pwd)/mm2_6133/MM2.json) && echo -E "${contents}" > $(pwd)/mm2_6133/MM2.json

userpass=$(cat mm2_6133/MM2.json | jq -r '.rpc_password')

echo "MM_CONF_PATH=/home/komodian/mm2/MM2.json" > mm2_6133/.env
echo "MM_COINS_PATH=/home/komodian/mm2/coins" >> mm2_6133/.env
echo "MM_LOG=/home/komodian/mm2/mm2.log" >> mm2_6133/.env
echo "USERPASS=${userpass}" >> mm2_6133/.env
echo "USER_ID=${USER_ID}" >> mm2_6133/.env
echo "GROUP_ID=${GROUP_ID}" >> mm2_6133/.env

echo "username=${USER}" > username

echo "Installing poetry..."
python3.10 -m pip install --user --upgrade pip cffi
python3.10 -m pip install --user poetry

LOCAL_BIN="$HOME/.local/bin"
mkdir -p "${LOCAL_BIN}"
if [[ ":$PATH:" != *":${LOCAL_BIN}:"* ]]; then
    export PATH="${LOCAL_BIN}:$PATH"
fi
if ! grep -qs "${LOCAL_BIN}" ~/.profile 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.profile
fi
if ! grep -qs "${LOCAL_BIN}" ~/.bashrc 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi
hash -r

poetry config virtualenvs.in-project true
poetry config keyring.enabled false

cd $(pwd)/api
poetry update
cd ..

echo "Setup Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh ./get-docker.sh
sudo groupadd docker
sudo usermod -aG docker $USER
newgrp docker
sudo systemctl enable docker.service
sudo systemctl enable containerd.service
sudo apt-get update
sudo apt-get install docker-compose-plugin
