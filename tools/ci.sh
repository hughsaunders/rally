#!/bin/bash -ex

# This script is designed to be run by an automated testing system such
# as Jenkins. It is not a general purpose install script and will exit on
# the first failure, as an indication of test failure.

# Target: Ubuntu 12.04/Precise Cloud instances

#VARIABLES
RALLY_DIR=${RALLY_DIR:-/opt/rally}
RALLY_REPO=https://git.openstack.org/stackforge/rally
DEPLOYMEMT_CONFIG=$RALLY_DIR/local_devstack_deployment.yaml
FLAVOR_ID=10 #Create new flavor with this ID
SCENARIOS_DIR=$RALLY_DIR/doc/samples/tasks
CI_SCENARIOS_DIR=$RALLY_DIR/ci_scenarios

#FUNCTIONS
setup_ssh(){
  mkdir -p $HOME/.ssh
  [ -f $HOME/.ssh/id_rsa ] || ssh-keygen -N '' -f ~/.ssh/id_rsa
  cat $HOME/.ssh/id_rsa.pub >> $HOME/.ssh/authorized_keys
  echo "StrictHostKeyChecking no" >> /etc/ssh/ssh_config

  # Jenkins mangles ssh config file?
  sed -ie 's/PermitRootLogin no//' /etc/ssh/sshd_config
  /etc/init.d/ssh restart

  # Check keys are setup correctly
  ssh root@localhost date
}

install_rally(){
  apt-get update
  apt-get -y install python-pip python-dev python-virtualenv build-essential libffi-dev jq git
  git clone $RALLY_REPO $RALLY_DIR
  virtualenv $RALLY_DIR/.venv
  source $RALLY_DIR/.venv/bin/activate
  pushd $RALLY_DIR
  pip install pbr
  pip install "tox<=1.6.1"
  pip install .
  rally-manage db recreate
}

create_devstack_deployment(){
  DEFAULT_INTERFACE=$(ip r |awk '/default/{print $5}')
  DEFAULT_IP=$(ip a l dev $DEFAULT_INTERFACE |awk '/inet[^6]/{print $2}'\
    |sed 's+/.*$++')
  cat > $DEPLOYMEMT_CONFIG <<EOF
---
name: DevstackEngine # Deploy using Devstack
provider:
  name: DummyProvider # Connect to existing server (localhost) via ssh.
  credentials:
    - user: root # assumes ssh keys are already in place.
      host: $DEFAULT_IP
EOF

  rally -dv deployment create --name devstack --filename $DEPLOYMEMT_CONFIG
  source ~/.rally/openrc
}

generate_scenario_configs(){
  CIRROS_ID=$(glance image-list |awk '$4 ~ /cirros.*uec$/{print $2}')
  nova flavor-create small $FLAVOR_ID 256 5 1
  mkdir ci_scenarios

  for SCENARIO_SET_PATH in $SCENARIOS_DIR/*; do
    SCENARIO_SET=$(basename $SCENARIO_SET_PATH)
    for SCENARIO_PATH in $SCENARIO_SET_PATH/*; do
      SCENARIO=$(basename $SCENARIO_PATH)
      jq '.[][]["args"]["image_id"]="'$CIRROS_ID'"|.[][]["args"]["flavor_id"]='$FLAVOR_ID\
        <$SCENARIO_PATH >ci_scenarios/${SCENARIO_SET}_${SCENARIO}
    done
  done
}

run_scenarios(){
  for TASK in $CI_SCENARIOS_DIR/*; do
    rally task start --task $TASK
  done
}

#MAIN
setup_ssh
install_rally
create_devstack_deployment
generate_scenario_configs
run_scenarios

