"""simple test for sinks.google.scripts.webhookReceiver

usage: mockgoogle-send.py [-h] url

positional arguments:
  url         url to send the data

optional arguments:
  -h, --help  show this help message and exit
"""

import argparse
import json
from datetime import datetime

import requests


parser = argparse.ArgumentParser()
parser.add_argument("url", help="url to send the data")
args = parser.parse_args()

payload = {"message" : "HELLO FROM **NOT** GOOGLE!!! DATE AND TIME:" + str(datetime.now())}
headers = {'content-type': 'application/json'}
r = requests.post(args.url, data = json.dumps(payload), headers = headers, verify=False)

print(r)
