#!/bin/bash

set -e

spc() {
    echo "From $PWD"
    echo "Executing ./venv-cmd.sh $1 $2 $3 $4 $5"
    sudo docker run -it --rm --privileged --pid host --ipc host --net host \
        -v /run:/run -v /etc/localtime:/etc/localtime \
        -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
        -v /:/host -w /host/$PWD pet \
        /bin/bash -c "./venv-cmd.sh $1 $2 $3 $4 $5" || exit 1
}

if [ "$1" == "install" ]
then
    rm -rf .venv
    rm -rf .cache
    echo "Setup pet testing container"
    cat << EOF > Dockerfile
FROM docker.io/ubuntu:latest
RUN apt-get update -qq && apt-get clean
RUN apt-get install -qq \
        realpath python3 python3-venv python-virtualenv docker.io \
        gcc openssl libxslt-dev libffi-dev python-dev \
        python3-dev libxml2-dev libselinux1 rsync yum-utils \
        python3-pycurl python-simplejson libssl-dev \
        zlib1g-dev && \
    apt-get clean
RUN mkdir -p $PWD
EOF
    trap "rm Dockerfile" EXIT
    cat Dockerfile | sudo docker build -t pet:latest -
    spc true || (cat artifacts/venv-cmd.sh.log && exit 1)
    spc ansible-galaxy install --force --role-file=requirements.yml
elif [ "$1" == "Typo Check" ]
then
    echo "$(git log -1 --format=%H origin/master)" > /tmp/start;
    echo "$(git log -1 --format=%H HEAD)" > /tmp/end;
    git log -p $(cat /tmp/start)..$(cat /tmp/end) -- . ':!.travis.yml' &> /tmp/commits;
    echo "Typos found:";
    egrep -a -i -2 "$TYPOS" /tmp/commits | tee /tmp/typos;
    test "$(cat /tmp/typos | wc -l)" -eq "0" || exit 1;
elif [ "$1" == "Unit test" ]
then
    echo "Run unittests";
    spc ./unittest.sh
elif [ "$1" == "System test" ]
then
    echo "Verify playbook executes using the defaults";
    spc ansible-playbook ./main.yml
    echo "Verify repository is left clean";
    echo "Failing if any repo. files left modified:";
    git status;
    git diff;
    test "$(git status --porcelain | wc -l)" -eq "0";
else
    echo "Unknowwn suite!";
    exit 1;
fi
