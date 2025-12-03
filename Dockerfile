FROM debian:stable-slim as fetcher
COPY build/fetch_binaries.sh /tmp/fetch_binaries.sh
RUN apt-get update && apt-get install -y \
  curl \
  wget \
  && rm -rf /var/lib/apt/lists/*
RUN /tmp/fetch_binaries.sh

FROM alpine:3.22.0
RUN set -ex \
    && echo "http://dl-cdn.alpinelinux.org/alpine/edge/main" >> /etc/apk/repositories \
    && echo "http://dl-cdn.alpinelinux.org/alpine/edge/testing" >> /etc/apk/repositories \
    && echo "http://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories \
    && apk update \
    && apk upgrade \
    && apk add --no-cache \
    apache2-utils \
    postgresql18-client \
    bash \
    bind-tools \
    bird \
    bridge-utils \
    busybox-extras \
    conntrack-tools \
    curl \
    dhcping \
    drill \
    ethtool \
    file\
    fping \
    iftop \
    iperf \
    iperf3 \
    iproute2 \
    ipset \
    iptables \
    iptraf-ng \
    iputils \
    ipvsadm \
    httpie \
    jq \
    libc6-compat \
    liboping \
    ltrace \
    mtr \
    net-snmp-tools \
    netcat-openbsd \
    nftables \
    ngrep \
    nmap \
    nmap-nping \
    nmap-scripts \
    openssl \
    py3-pip \
    py3-setuptools \
    scapy \
    socat \
    speedtest-cli \
    openssh \
    oh-my-zsh \
    strace \
    tcpdump \
    tcptraceroute \
    trippy \
   # tshark \
    util-linux \
    vim \
    git \
    zsh \
    websocat \
    swaks \
    perl-crypt-ssleay \
    perl-net-ssleay \
    yq \
    k9s \
    pigz \
    screen \
    helm \
    wget \
    mc \
    aws-cli && \
    rm -rf /var/cache/apk/*
# Download and install oc
#RUN curl -LO https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz \
#  && tar -xzf openshift-client-linux.tar.gz \
#  && mv oc kubectl /usr/local/bin/ \
# && rm openshift-client-linux.tar.gz README.md
# Install MongoDB database tools
RUN curl -L "https://fastdl.mongodb.org/tools/db/mongodb-database-tools-debian11-x86_64-100.13.0.tgz" -o /tmp/mongo-tools.tgz \
    && tar -xzf /tmp/mongo-tools.tgz -C /tmp \
    && mv /tmp/mongodb-database-tools-debian11-x86_64-100.13.0/bin/* /usr/local/bin/ \
    && rm -rf /tmp/mongo-tools.tgz /tmp/mongodb-database-tools-debian11-x86_64-100.13.0
RUN helm plugin install https://github.com/datarobot-oss/helm-datarobot-plugin.git && helm plugin update datarobot

COPY --from=fetcher \
    /tmp/ctop \
    /tmp/calicoctl \
   # /tmp/termshark \
    /tmp/grpcurl \
    /tmp/fortio \
    /tmp/oc \
    /tmp/kubectl \
    /tmp/mongodump \
    /tmp/mongorestore \
    /tmp/mongosh \
   # /tmp/aws-cli/v2/current/bin/aws \
    /tmp/mcli \
    /usr/local/bin/
# Setting User and Home
USER root
WORKDIR /root
ENV HOSTNAME netshoot

# Install dr-utils 
COPY dr-util/* /usr/local/bin/
RUN chmod +x -R /usr/local/bin/ ; mkdir support-scripts; git clone https://github.com/datarobot-oss/support-scripts.git support-scripts
# Install support-scripts
COPY integration tests
# ZSH Themes
RUN curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh | sh
RUN git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
RUN git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k
COPY zshrc .zshrc
COPY motd motd

# Fix permissions for OpenShift and tshark
RUN chmod -R g=u /root
#RUN chown root:root /usr/bin/dumpcap

# Running ZSH
CMD ["zsh"]
