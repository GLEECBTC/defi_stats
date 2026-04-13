FROM komodoofficial/komodo-defi-framework:dev-latest

LABEL maintainer="smk@komodoplatform.com"

# Setup up user and working directory
ARG DEBIAN_FRONTEND=noninteractive 
ARG GROUP_ID
ARG USER_ID
RUN apt-get update && apt-get install -y --no-install-recommends adduser \
&& addgroup --gid ${GROUP_ID} notarygroup \
&& adduser --disabled-password --gecos '' --uid ${USER_ID} --gid ${GROUP_ID} komodian

WORKDIR /home/komodian/mm2

# Install dependencies
ARG DEBIAN_FRONTEND=noninteractive 
RUN apt update && apt install nano htop procps sqlite3 -y

ENV MM_CONF_PATH=/home/komodian/mm2/MM2.json
ENV MM_COINS_PATH=/home/komodian/mm2/coins
ENV MM_LOG=/home/komodian/mm2/mm2_8762.log
ENV USERPASS=${userpass}
ENV RUST_LOG="info,libp2p_gossipsub::behaviour=off,mm2_p2p::behaviours=off,mm2_main::mm2::lp_network=off"
#mm2_main::mm2::rpc=off,mm2_libp2p::peers_exchange=off,rustls::check=off,rustls::conn=off,mm2_libp2p::atomicdex_behaviour=off,coins::utxo::utxo_builder::utxo_coin_builder=warn"

ENV PATH=/app:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Setup user and working directory
RUN chown -R komodian:notarygroup /home/komodian
USER komodian