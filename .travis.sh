#!/bin/bash

set -e

export WORKSPACE=/var/tmp/workspace
export ARTIFACTS="$WORKSPACE/artifacts"
sudo rm -rf $WORKSPACE/*
sudo mkdir -p $WORKSPACE
sudo chmod 1777 $WORKSPACE

spc() {
    echo "From $PWD"
    # Dunno why $@ doesn't work here for some reason
    echo "Executing ./venv-cmd.sh $1 $2 $3 $4 $5"
    sudo docker run -it --rm --privileged --pid host --ipc host --net host \
        -e PYTHON3SUPPORT=true \
        -v /run:/run -v /etc/localtime:/etc/localtime \
        -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
        -v /:/host -w /host/$PWD \
        -v $WORKSPACE:$WORKSPACE:Z \
        pet \
        /bin/bash -c "./bin/venv-cmd.sh $1 $2 $3 $4 $5" || exit 1
}

if [ "$1" == "install" ]
then
    echo "Setup pet testing container"
    cat << EOF > /tmp/Dockerfile
FROM docker.io/ubuntu:latest
RUN apt-get update -qq && apt-get clean
RUN apt-get install -qq \
        realpath python3 python3-venv python-virtualenv docker.io \
        gcc openssl libxslt-dev libffi-dev python-dev \
        python3-dev libxml2-dev libselinux1 rsync yum-utils \
        python3-pycurl python-simplejson libssl-dev \
        zlib1g-dev && \
    apt-get clean
ENV WORKSPACE=$WORKSPACE
ENV ARTIFACTS=$ARTIFACTS
RUN mkdir -p $PWD && \
    mkdir -p /var/tmp/workspace
VOLUME ["$WORKSPACE"]
EOF
    cat /tmp/Dockerfile | sudo docker build -t pet:latest -
    spc ansible-galaxy install --force --role-file=requirements.yml
elif [ "$1" == "Typo Check" ]
then
    TYPOS='ec-oh | ro-el | FI-XME'
    if [ "${TRAVIS_BRANCH:-master}" == "master" ]; then
        TYPOS="${TYPOS} | fix-up! | s-qua-sh!"
    fi
    TYPOS=$(echo "$TYPOS" | tr -d ' -')
    ANCESTOR=$(git merge-base origin/master HEAD)
    if [ $ANCESTOR == $(git rev-parse HEAD) ]; then
        ANCESTOR=HEAD^
    fi
    echo "Checking against ${ANCESTOR} for conflict and whitespace problems:"
    git diff --check ${ANCESTOR}..HEAD  # Silent unless problem detected
    git log -p ${ANCESTOR}..HEAD -- . ':!.travis.*' &> /tmp/commits_with_diffs
    LINES=$(wc -l </tmp/commits_with_diffs)
    if (( $LINES == 0 ))
    then
        echo "FATAL: no changes found since ${ANCESTOR}"
        exit 3
    fi
    echo "Examining $LINES change lines for typos:"
    set +e
    egrep -a -i -2 --color=always "$TYPOS" /tmp/commits_with_diffs && exit 3
    exit 0
elif [ "$1" == "Unit test" ]
then
    echo "Run unittests";
    spc ./bin/unittest.sh
elif [ "$1" == "System test" ]
then
    echo "Verify playbook executes using the defaults";
    spc ansible-playbook ./main.yml
    echo "Verify repository is left clean";
    echo "Failing if any repo. files left modified:";
    git status;
    test "$(git status --porcelain | wc -l)" -eq "0";
else
    echo "Unknowwn suite!";
    exit 1;
fi
