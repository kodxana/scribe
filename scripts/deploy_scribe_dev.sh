#!/usr/bin/env bash

# usage: deploy_scribe_dev.sh <host to update>
TARGET_HOST=$1

SCRIPTS_DIR=`dirname $0`
SCRIBE_DIR=`dirname $SCRIPTS_DIR`

# build the image
docker build -f $SCRIBE_DIR/docker/Dockerfile -t lbry/scribe:development $SCRIBE_DIR
IMAGE=`docker image inspect lbry/scribe:development | sed -n "s/^.*Id\":\s*\"sha256:\s*\(\S*\)\".*$/\1/p"`

# push the image to the server
ssh $TARGET_HOST docker image prune --force
docker save $IMAGE | ssh $TARGET_HOST docker load
ssh $TARGET_HOST docker tag $IMAGE lbry/scribe:development

## restart the wallet server
ssh $TARGET_HOST SCRIBE_TAG="development" docker-compose up -d
