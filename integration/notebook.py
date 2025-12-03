#!/usr/bin/env python3
import json
import os
import argparse
from pprint import pprint
import requests
import time
import sys
import urllib3
urllib3.disable_warnings()
from kubernetes import client, config
import base64
from datetime import datetime


data = {
	"cells": [
		{
			"cell_type": "code",
			"source": "1+1",
			"metadata": {
				"name": "First cell",
				"scrolled": "auto",
				"datarobot": {
					"language": "python"
				},
			},
		}
	]
}

def _request(method, api_key, url, json=None):
    response = getattr(requests, method)(url, headers={"Authorization": f"Bearer {api_key}"},
                                         json=json,

                                         )
    if not response.ok:
        print("Invalid Response", response.content)
        sys.exit(1)
    return response

def main(argv):
    print(argv)
    if argv.url == "" and argv.apikey == "":
        print("read config from NS: {}".format(argv.ns))
        config.load_kube_config()
        v1 = client.CoreV1Api()
        sec = v1.read_namespaced_secret("ui-admin-credentials", argv.ns).data
        k8s_cfg = {}
        for k in sec.keys():
            k8s_cfg[k] = base64.b64decode(sec[k]).decode()
        print(k8s_cfg)
        base_url = k8s_cfg["fqdn"]
        os.environ["DATAROBOT_API_TOKEN"] = k8s_cfg["api_key"]
    else:
        print("using static creds for {}".format(argv.url))
        base_url = argv.url
        os.environ["DATAROBOT_API_TOKEN"] = argv.apikey

    os.environ["DATAROBOT_SSL_VERIFY"] = str(not(argv.insecure))
    host = "https://{}/".format(base_url)
    api_key = os.environ["DATAROBOT_API_TOKEN"]
    print("**** start ****")
    url_prefix = f"{host}/api-gw/nbx"
    # data = {"name": f"Test Notebook", "createInitialCell": True}
    # create_notebook_response = _request('post', api_key, f"{url_prefix}/notebooks/", data)
    # notebook_id = create_notebook_response.json()['id']

    headers = {
        'Authorization': f'Bearer {api_key}',
    }
    files = {'file': open('./data/notebook.ipynb', 'rb')}
    response = requests.post(f'{url_prefix}/notebookImport/fromFile/', headers=headers, files=files, verify=not(argv.insecure))
    if response.status_code not in [200, 201]:
        print(f"failed Notebook import file")
        print(response.status_code)
        print(response.text)
        sys.exit(1)
    data = response.json()
    print("notebook imported")
    notebook_id = data["id"]


    _request('post', api_key, f"{host}/api-gw/nbx/orchestrator/notebooks/{notebook_id}/start")
    start = time.time()

    started = False
    while not started:
        get_session_response = _request('get', api_key, f"{host}/api-gw/nbx/orchestrator/notebooks/{notebook_id}/")
        r = get_session_response.json()
        print(r['status'])
        # print(get_session_response.json())
        if r['status'] == 'running':
            end = time.time()
            started = True
        if time.time() - start > 60 * 10:
            print(f"Notebook  hasn't started in 10 minutes")
            break
        time.sleep(1)
    else:
        print(f"Notebook  launch took", round(end - start, 2), "seconds")

    print(f"Notebook deleting {notebook_id}")
    _request('delete', api_key, f"{host}/api-gw/nbx/notebooks/{notebook_id}/")



if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument('-n', '--ns', default=os.environ.get("NS", "dr-app-charts-master-daily"))
    p.add_argument('-u', '--url', default="")
    p.add_argument('-a', '--apikey', default="")
    p.add_argument("-i","--insecure", action="store_true", default=False)

    args = p.parse_args()
    start_time = datetime.now()
    main(args)
    end_time = datetime.now()
    print("Duration: {}".format(end_time - start_time))
