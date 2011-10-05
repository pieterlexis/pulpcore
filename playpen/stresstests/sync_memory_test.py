#!/usr/bin/python
#
# Copyright (c) 2011 Red Hat, Inc.
#
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.


#TODO:  Allow this script to run as 'apache' so it has the correct permissions for /var/lib/pulp, /var/log/pulp
#Workaround:  Run as root
#             then "chmod -R apache /var/lib/pulp, chmod -R apache /var/log/pulp" 
#             after we are done testing to restore permissions for Apache

import optparse
import os
import sys
import time

# Load Pulp code from git checkout instea
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../../src")

from pulp.server import async
from pulp.server.api import repo_sync
from pulp.server.api.repo import RepoApi
from pulp.server.tasking import task
from pulp.server.webservices import application

# Initialize Pulp
application._initialize_pulp()

TIME_FMT_STR = "%b%d_%Y__%l:%M%p"
REPO_API = RepoApi()

def parse_feed_urls(file_name):
    """
    Expecting a file in the format of:
     Each line contains: repo_id, feed_url, feed_ca, feed_cert
    """
    feed_urls = []
    f = open(file_name, "r")
    try:
        raw_lines = f.readlines()
        for line in raw_lines:
            pieces = line.strip().split(",")
            feed = {}
            feed["id"] = pieces[0].strip()
            feed["url"] = pieces[1].strip()
            feed["feed_ca"] = pieces[2].strip()
            feed["feed_cert"] = pieces[3].strip()
            feed_urls.append(feed)
    finally:
        f.close()
    return feed_urls

def create_repos(repos_to_sync):
    for repo in repos_to_sync:
        if not REPO_API.repository(repo["id"]):
            print "Create repository %s with feed %s" % (repo["id"], repo["url"])
            f = open(repo["feed_ca"], "r")
            try:
                ca = f.read()
            finally:
                f.close()
            f = open(repo["feed_cert"], "r")
            try:
                cert = f.read()
            finally:
                f.close()
            REPO_API.create(repo["id"], repo["id"], feed=repo["url"], arch="noarch",
                    feed_cert_data={"ca":ca, "cert":cert},
                    preserve_metadata=True)

def sync_repos(repos_to_sync):
    sync_tasks = []
    # Create sync tasks for all Repos
    for repo in repos_to_sync:
        sync_task = repo_sync.sync(repo["id"])
        if not sync_task:
            print "%s failed to create a repo sync task for: %s" % (time.strftime(TIME_FMT_STR), repo["id"])
        sync_tasks.append(sync_task)
    # Wait for all sync tasks to complete
    wait_for_complete = True
    while wait_for_complete:
        time.sleep(5)
        wait_for_complete = False
        for t in sync_tasks:
            updated_task = async.find_async(id=t.id)
            if not updated_task or len(updated_task) < 1:
                print "Error task lookup up: %s" % (t)
                continue
            # If any tasks have not completed, wait
            if updated_task[0].state not in task.task_complete_states:
                wait_for_complete = True

if __name__ == "__main__":
    print "%s start sync test" % (time.strftime(TIME_FMT_STR))
    parser = optparse.OptionParser()
    parser.add_option('--feed_urls', action='store',
        help='Required parameter, file path for feed_urls')
    parser.add_option('--num_syncs', action='store',
        help='If specified will loop over this many syncs instead of an infinite loop', default="0")
    (opts, args) = parser.parse_args()
    if not opts.feed_urls:
        parser.print_help()
        print "Missing required parameter --feed_urls"
        sys.exit(1)

    # Parse feed_urls
    repos_to_sync = parse_feed_urls(opts.feed_urls)

    # Create repos or reuse if they exist
    create_repos(repos_to_sync)

    # Sync repos
    num_syncs = int(opts.num_syncs)
    if num_syncs > 0:
        for index in range(0, num_syncs):
            print "%s %s full iteration" % (time.strftime(TIME_FMT_STR), index)
            sync_repos(repos_to_sync)

    else:
        count = 0
        while True:
            print "%s %s full iteration" % (time.strftime(TIME_FMT_STR), count)
            sync_repos(repos_to_sync)
            count = count + 1

    print "%s end sync test" % (time.strftime(TIME_FMT_STR))
