#!/bin/python3

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#                                                                           #
#   OpenBench is a chess engine testing framework by Andrew Grant.          #
#   <https://github.com/AndyGrant/OpenBench>  <andrew@grantnet.us>          #
#                                                                           #
#   OpenBench is free software: you can redistribute it and/or modify       #
#   it under the terms of the GNU General Public License as published by    #
#   the Free Software Foundation, either version 3 of the License, or       #
#   (at your option) any later version.                                     #
#                                                                           #
#   OpenBench is distributed in the hope that it will be useful,            #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#   GNU General Public License for more details.                            #
#                                                                           #
#   You should have received a copy of the GNU General Public License       #
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.   #
#                                                                           #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

import argparse
import cpuinfo
import os
import re
import requests
import sys

# Needed to include from ../Client/*.py
PARENT = os.path.join(os.path.dirname(__file__), os.path.pardir)
sys.path.append(os.path.abspath(PARENT))

from Client.utils import *
from bench_engine import run_benchmark

def get_default_network(args, network):

    # Download the default Network
    net_name = network['name']
    net_sha  = network['sha']
    net_path = os.path.join('Networks', net_sha)
    download_network(args.server, args.username, args.password, engine, net_name, net_sha, net_path)

    return net_path

def get_public_engine(engine, config):

    make_path = config['build']['path']
    branch    = config['test_presets']['default']['base_branch']
    out_path  = os.path.join('Engines', engine)
    target    = url_join(config['source'], 'archive', '%s.zip' % (branch))

    net_sha   = config.get('network', {}).get('sha')
    net_path  = os.path.join('Networks', net_sha) if net_sha else None

    try:
        download_public_engine(engine, net_path, branch, target, make_path, out_path)

    except OpenBenchBuildFailedException as error:
        print ('Failed to build %s...\n\nCompiler Output:' % (engine))
        for line in error.message.split('\n'):
            print ('> %s' % (line))
        print ()

def get_private_engine(engine, config):

    out_path = os.path.join('Engines', engine)
    branch   = config['test_presets']['default']['base_branch']

    # Format an API request to get the most recent openbench.yml workflow on the primary branch
    api_repo = config['source'].replace('github.com', 'api.github.com/repos')
    target   = url_join(api_repo, 'actions/workflows/openbench.yml/runs', trailing_slash=False)
    target  += '?branch=%s' % (branch)

    # Use the run_id for the primary branch's openbench.yml workflow to locate the artifacts
    headers  = read_git_credentials(engine)
    run_id   = requests.get(url=target, headers=headers).json()['workflow_runs'][0]['id']
    source   = url_join(api_repo, 'actions/runs/%d/artifacts' % (run_id), trailing_slash=False)

    # Selecting an artifact requires knowledge of the CPU
    cpu_info  = cpuinfo.get_cpu_info()
    cpu_name  = cpu_info.get('brand_raw', cpu_info.get('brand', 'Unknown'))
    cpu_flags = [x.replace('_', '').replace('.', '').upper() for x in cpu_info.get('flags', [])]

    try:
        download_private_engine(engine, branch, source, out_path, cpu_name, cpu_flags, None)

    except OpenBenchMissingArtifactExceptionException as error:
        print ('Failed to download %s... %s', engine, error.message)

if __name__ == '__main__':

    # Use bench_all.py's path as the base pathway
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Ensure the folder structure for ease of coding
    for folder in ['Engines', 'Networks']:
        if not os.path.isdir(folder):
            os.mkdir(folder)

    # credentialed_cmdline_args() adds --user, --password, and --server
    parser = argparse.ArgumentParser()
    parser.add_argument('--rebuild', help='Forcefully rebuild all engines', action='store_true')
    parser.add_argument('--regex',   help='Regex to match Engine names')
    parser.add_argument('--engines', help='List of specific engines', nargs='+')
    parser.add_argument('--threads', help='Concurrent Benchmarks',  required=True, type=int)
    parser.add_argument('--sets'   , help='Benchmark Sample Count', required=True, type=int)
    args   = credentialed_cmdline_args(parser)

    # Get the build info, and default network info, for all applicable engines
    request = credentialed_request(args.server, args.username, args.password, 'api/buildinfo')
    configs = request.json()

    # Filter down to only engines provided via --engines, if applicable
    engines = configs.keys() if not args.engines else args.engines
    engines = list(set(engines) & set(configs.keys()))

    # Filter down to only engines matching --regex, if applicable
    if args.regex:
        engines = list(filter(lambda x: re.match(args.regex, x), engines))

    # Delete any existing engines that are to be rebuilt
    if args.rebuild:
        for engine in engines:
            if (bin_path := check_for_engine_binary(os.path.join('Engines', engine))):
                os.remove(bin_path)

    # Get all the default Network files for the engines
    for engine in engines:
        if configs[engine].get('network'):
            get_default_network(args, configs[engine]['network'])

    # Download artifacts for Private engines
    for engine in engines:
        if configs[engine]['private']:
            get_private_engine(engine, configs[engine])

    # Download source and build Public engines
    for engine in engines:
        if not configs[engine]['private']:
            get_public_engine(engine, configs[engine])

    for engine in engines:

        # Builds may have failed in previous steps, which we can ignore
        if not (bin_path := check_for_engine_binary(os.path.join('Engines', engine))):
            print ('Unable to find binary for %s...' % (engine))
            continue

        # Private engines need to set the Network from the command line
        private_net = configs[engine]['private'] and configs[engine].get('network')
        net_path    = os.path.join('Networks', configs[engine]['network']['sha']) if private_net else None

        nps, nodes = run_benchmark(bin_path, net_path, args.threads, args.sets)
        print ('%s %d nps %d nodes in %.3f seconds' % (engine, nps, nodes, nodes / max(1e-6, nps)))
