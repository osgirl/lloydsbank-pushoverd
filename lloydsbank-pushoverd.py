#!/usr/bin/env python
# lloydsbank-pushoverd.py - Receive pushover notification with your Lloyds Bank account balance.
# This file is part of lloydsbank-pushoverd.
# Copyright (c) 2014 Tomasz Jan Góralczyk <tomg@fastmail.uk>
# License: MIT
from __future__ import print_function
import argparse
import json
import sys

# Is verbose?
VERBOSE = False

# Parse commandline arguments.
def parse_commandline():
    # Create parser.
    parser = argparse.ArgumentParser(
            description='Receive pushover notification with your Lloyds Bank account balance.')
    parser.add_argument('config', metavar='config-file.json', type=file,
            help='path to the configuration file')
    parser.add_argument('-v', '--verbose', action='store_true', help='enable verbose logging')
    parser.add_argument('-f', '--force', action='store_true',
            help='send notification even if no new transactions are found')

    # Parse and return arguments.
    return parser.parse_args()

# Parse configuration file.
# f - File handle to configuration file.
def parse_configuration(f):
    global VERBOSE

    if VERBOSE:
        print('Reading configuration file', file=sys.stderr)
    # Read configuration from file.
    config = json.load(f)

    # Close the file.
    if VERBOSE:
        print('Closing configuration file', file=sys.stderr)
    f.close()

    # Return config.
    return config

def main():
    global VERBOSE
    # Parse command-line options.
    args = parse_commandline()
    VERBOSE = args.verbose
    # Load configuration file.
    parse_configuration(args.config)

if __name__ == '__main__':
    main()
