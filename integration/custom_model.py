#!/usr/bin/env python3
import json
import os
from pathlib import Path
from pprint import pprint
import requests
import sys
import datarobot as dr
import time
import optparse
import urllib3
urllib3.disable_warnings()
from kubernetes import client, config
import base64
from datetime import datetime
import csv


ENV_NAME= "Skel"
dataset_file_path = Path(".").parent.joinpath("data", "boston_housing.csv")
py3skle_file_path = Path(".").parent.joinpath("data", "py3sklearnenvironment.tar.gz")
model_file_path = Path(".").parent.joinpath("data", "custom_model")


def main(namespace="default", cleanup=True,argv=None):

    config.load_kube_config()
    v1 = client.CoreV1Api()
    sec = v1.read_namespaced_secret("ui-admin-credentials", namespace).data
    print(base64.b64decode(sec["fqdn"]).decode())
    print(base64.b64decode(sec["password"]).decode())

    base_url = base64.b64decode(sec["fqdn"]).decode()
    os.environ["DATAROBOT_ENDPOINT"]= "https://{}/api/v2/".format(base_url)
    os.environ["DATAROBOT_API_TOKEN"] = base64.b64decode(sec["api_key"]).decode()
    os.environ["DATAROBOT_SSL_VERIFY"]= str(not(argv.insecure))

    print("start")
    for attempts in range(3):
        try:
            dr.Client()
        except dr.errors.ServerError as e:
            print("[{}] Error : {}".format(attempts, e))
            time.sleep(1)
    datasets = dr.Dataset.list()
    dataset = False
    for d in datasets:
        if d.name == "boston_housing.csv":
            print("found dataset to AI Catalog")
            dataset = d
            break

    if dataset == False:
        print("Upload dataset to AI Catalog")
        dataset = dr.Dataset.create_from_file(file_path=dataset_file_path)

    envs = dr.ExecutionEnvironment.list(search_for=ENV_NAME)
    if len(envs) == 1:
        print("found existing Env")
        execution_environment = envs[0]
        environment_version = dr.ExecutionEnvironmentVersion.list(
            execution_environment.id
        )[0]


    else:
        print("creating a new Env")
        execution_environment = dr.ExecutionEnvironment.create(
            name=ENV_NAME,
            description=ENV_NAME,
        )

        print("creating a new Env Version")
        environment_version = dr.ExecutionEnvironmentVersion.create(
            execution_environment.id,
            docker_context_path=py3skle_file_path,
            max_wait=None
        )

    while True:
        environment_version.refresh()
        print(environment_version.build_status)

        if environment_version.build_status == "submitted":
            continue
        elif environment_version.build_status != "processing":
            break

        time.sleep(5)



    if environment_version.build_status != "success":
        print("env status {}".format(environment_version.build_status))
        if cleanup:
            execution_environment.delete()

    if environment_version.build_status == "failed":
        print(" ERROR env status {}".format(environment_version.build_status))
        sys.exit(1)



    inf_name="skel Custom Model"
    custom_models = dr.CustomInferenceModel.list(
        search_for=inf_name,
    )
    if len(custom_models) == 1:
        print("found CustomInferenceModel")
        custom_model = custom_models[0]
    else:
        print("creating CustomInferenceModel")
        custom_model = dr.CustomInferenceModel.create(
            name=inf_name,
            target_type=dr.TARGET_TYPE.REGRESSION,
            target_name='MEDV',
            description=inf_name,
            language='python'
        )


    model_versions = dr.CustomModelVersion.list(custom_model.id)
    if len(model_versions) == 1:
        model_version = model_versions[0]
    else:
        model_version = dr.CustomModelVersion.create_clean(
            custom_model_id=custom_model.id,
            base_environment_id=execution_environment.id,
            folder_path=model_file_path,
        )


    test_done = False
    cm_tests = dr.CustomModelTest.list(custom_model_id=custom_model.id)
    if len(cm_tests) > 1:
        print("found {} tests".format(len(cm_tests)))
        custom_model_test = cm_tests[-1] # get last test

        print("test already executed with result : {}".format(custom_model_test.overall_status))
        if custom_model_test.overall_status != "failed":
            test_done = True


    if not test_done:
        print("run test custom model")
        custom_model_test = dr.CustomModelTest.create(
            custom_model_id=custom_model.id,
            custom_model_version_id=model_version.id,
            dataset_id=dataset.id,
            max_wait=3600,  # 1 hour timeout
        )
        print("test executed with result : {}".format(custom_model_test.overall_status))



    if custom_model_test.overall_status == "failed":
        print("custom_model_test.overall_status {}".format(custom_model_test.overall_status))
        sys.exit(1)



    prediction_server = dr.PredictionServer.list()[0]

    deployments = dr.Deployment.list()
    deployment = False
    for d in deployments:
        if d.label == ENV_NAME:
            print("found existing Deployment")
            deployment = d


    if deployment == False:
        print("create Deployment")
        deployment = dr.Deployment.create_from_custom_model_version(
            custom_model_version_id=model_version.id,
            default_prediction_server_id=prediction_server.id,
            label=ENV_NAME,
            max_wait=600
        )


    # Step 3: Make predictions
    lst = []
    with open(dataset_file_path, mode='r') as f:
        data = csv.reader(f, skipinitialspace=True)
        h = next(data)
        for row in data:
            lst.append(dict(zip(h, row)))
            if len(lst) > 3:
                break

    prediction_headers = {
        "Authorization": "Bearer {}".format(os.environ["DATAROBOT_API_TOKEN"]),
        "Content-Type": "application/json",
        "datarobot-key": prediction_server.datarobot_key,
    }

    total = 10
    for x in range(total):
        print("Sending requests {}/{}".format((x + 1) , total))
        predictions = requests.post(
            "https://{}/predApi/v1.0/deployments/{}/predictions".format(base_url, deployment.id),
            headers=prediction_headers,
            data=json.dumps(lst),
            verify=not(argv.insecure),
        )
        if predictions.status_code != 200:
            print (' - ERROR on prediction got HTTP :{}'.format(predictions.status_code))

    # Step 4: Monitor deployment
    service_stats = deployment.get_service_stats()
    pprint(service_stats.metrics)
    if service_stats.metrics.get("totalRequests", 0) == 0:
        print(" !!!! WARNING !!!! is not working as planned")

    if cleanup:
        print("cleanup")
        print(" deleting deployment")
        deployment.delete()
        print(" deleting custom model")
        custom_model.delete()
        print(" deleting execution_environment")
        execution_environment.delete()


if __name__ == '__main__':
    p = optparse.OptionParser()
    p.add_option('-c', '--clean', action="store_true", default=False)
    p.add_option('-n', '--ns', default="dr-app-charts-master-daily")
    p.add_option("-i","--insecure", action="store_true", default=False)
    options, arguments = p.parse_args()
    start_time = datetime.now()
    main(namespace=options.ns, cleanup=options.clean, argv=options)
    end_time = datetime.now()
    print('Duration: {}'.format(end_time - start_time))
