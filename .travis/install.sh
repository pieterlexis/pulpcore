#!/usr/bin/env bash

# WARNING: DO NOT EDIT!
#
# This file was generated by plugin_template, and is managed by it. Please use
# './plugin-template --travis pulpcore' to update this file.
#
# For more info visit https://github.com/pulp/plugin_template

set -euv

if [ "$TEST" = 'docs' ]; then
  pip install psycopg2-binary
  pip install -r doc_requirements.txt
fi

pip install -r functest_requirements.txt

cd $TRAVIS_BUILD_DIR/../pulpcore/containers/

# Although the tag name is not used outside of this script, we might use it
# later. And it is nice to have a friendly identifier for it.
# So we use the branch preferably, but need to replace the "/" with the valid
# character "_" .
#
# Note that there are lots of other valid git branch name special characters
# that are invalid in image tag names. To try to convert them, this would be a
# starting point:
# https://stackoverflow.com/a/50687120
#
# If we are on a tag
if [ -n "$TRAVIS_TAG" ]; then
  TAG=$(echo $TRAVIS_TAG | tr / _)
# If we are on a PR
elif [ -n "$TRAVIS_PULL_REQUEST_BRANCH" ]; then
  TAG=$(echo $TRAVIS_PULL_REQUEST_BRANCH | tr / _)
# For push builds and hopefully cron builds
elif [ -n "$TRAVIS_BRANCH" ]; then
  TAG=$(echo $TRAVIS_BRANCH | tr / _)
  if [ "${TAG}" = "master" ]; then
    TAG=latest
  fi
else
  # Fallback
  TAG=$(git rev-parse --abbrev-ref HEAD | tr / _)
fi


if [ -e $TRAVIS_BUILD_DIR/../pulp_file ]; then
  PULP_FILE=./pulp_file
else
  PULP_FILE=git+https://github.com/pulp/pulp_file.git@master
fi

if [ -e $TRAVIS_BUILD_DIR/../pulp-certguard ]; then
  PULP_CERTGUARD=./pulp-certguard
else
  PULP_CERTGUARD=git+https://github.com/pulp/pulp-certguard.git@master
fi

cat > vars/vars.yaml << VARSYAML
---
images:
  - pulp_file-${TAG}:
      image_name: pulp_file
      tag: "${TAG}"
      pulpcore: ./pulpcore
      plugins:
        - $PULP_FILE
        - $PULP_CERTGUARD
VARSYAML

if [ "$TEST" = 's3' ]; then
  echo "s3_test: true" >> vars/vars.yaml
fi

ansible-playbook -v build.yaml

cd $TRAVIS_BUILD_DIR/../pulp-operator
# Tell pulp-perator to deploy our image
# NOTE: With k3s 1.17, ${TAG} must be quoted. So that 3.0 does not become 3.
# NOTE: We use 1 pulp-content replica because some plugins need to pass
# commands to it to modify it, similar to the pulp-api container.
cat > deploy/crds/pulpproject_v1alpha1_pulp_cr.yaml << CRYAML
apiVersion: pulpproject.org/v1alpha1
kind: Pulp
metadata:
  name: example-pulp
spec:
  pulp_file_storage:
    # k3s local-path requires this
    access_mode: "ReadWriteOnce"
    # We have a little over 40GB free on Travis VMs/instances
    size: "40Gi"
  image: pulp_file
  tag: "${TAG}"
  database_connection:
    username: pulp
    password: pulp
    admin_password: pulp
  pulp_content:
    replicas: 1
  pulp_settings:
     allowed_export_paths: ['/tmp']
     allowed_import_paths: ['/tmp']
    
CRYAML

if [ "$TEST" = 's3' ]; then
  cat > deploy/crds/pulpproject_v1alpha1_pulp_cr.yaml << CRYAML
  apiVersion: pulpproject.org/v1alpha1
  kind: Pulp
  metadata:
    name: example-pulp
  spec:
    pulp_file_storage:
      # k3s local-path requires this
      access_mode: "ReadWriteOnce"
      # We have a little over 40GB free on Travis VMs/instances
      size: "40Gi"
    image: pulp_file
    tag: "${TAG}"
    database_connection:
      username: pulp
      password: pulp
      admin_password: pulp
    pulp_content:
      replicas: 1
    pulp_settings:
      allowed_export_paths: ['/tmp']
      allowed_import_paths: ['/tmp']
      aws_access_key_id: "AKIAIT2Z5TDYPX3ARJBA"
      aws_secret_access_key: "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"
      aws_storage_bucket_name: "pulp3"
      aws_default_acl: "@none None"
      s3_use_sigv4: true
      aws_s3_signature_version: "s3v4"
      aws_s3_addressing_style: "path"
      aws_s3_region_name: "eu-central-1"
      default_file_storage: "storages.backends.s3boto3.S3Boto3Storage"
      media_root: ''
      aws_s3_endpoint_url: "http://$(hostname):9000"

CRYAML
fi

# Install k3s, lightweight Kubernetes
.travis/k3s-install.sh
# Deploy pulp-operator, with the pulp containers, according to CRYAML
sudo ./up.sh

# Needed for the script below
# Since it is being run during install rather than actual tests (unlike in
# pulp-operator), and therefore does not trigger the equivalent after_failure
# travis commands.
show_logs_and_return_non_zero() {
    readonly local rc="$?"

    for containerlog in "pulp-api" "pulp-content" "pulp-resource-manager" "pulp-worker"
    do
      echo -en "travis_fold:start:$containerlog"'\\r'
      sudo kubectl logs -l app=$containerlog --tail=10000
      echo -en "travis_fold:end:$containerlog"'\\r'
    done

    return "${rc}"
}
.travis/pulp-operator-check-and-wait.sh || show_logs_and_return_non_zero
