userpass=$(cat MM2.json | jq -r '.rpc_password')
curl --url "http://127.0.0.1:7783" --data "{\"method\":\"get_directly_connected_peers\",\"userpass\":\"$userpass\"}"
echo ""
