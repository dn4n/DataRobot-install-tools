#!/usr/bin/env python3
import json
import os
from pathlib import Path
from pprint import pprint
import requests
import time
import sys
import datarobot as dr
import optparse
import urllib3
urllib3.disable_warnings()
from kubernetes import client, config
import base64
from datetime import datetime
import csv
import urllib.request
from io import StringIO



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

    os.environ["DATAROBOT_ENDPOINT"]= "https://{}/api/v2/".format(base_url)
    os.environ["DATAROBOT_SSL_VERIFY"]= str(not(argv.insecure))
    print("**** start ****")

    cfg = {
        "url": "https://s3.amazonaws.com/datarobot-use-case-datasets/10k_diabetes.csv",
        "target": "readmitted",
        "name": "10k_diabetes",
        "model_type": "Light Gradient Boosted Trees Classifier with Early Stopping"
    }

    if argv.upload:
        print("downloading {}".format(cfg["url"]))
        local_file = os.path.basename(cfg["url"])
        urllib.request.urlretrieve(cfg["url"], local_file)
        sourcedata = Path(".").parent.joinpath(local_file)
        print("using local file {}".format(sourcedata))
    else:
        print("using url {}".format(cfg["url"]))
        sourcedata = cfg["url"]

    # # Step 1: Upload a dataset
    for attempts in range(3):
        try:
            dr.Client()
        except dr.errors.ServerError as e:
            print("[{}] Error : {}".format(attempts, e))
            time.sleep(1)

    search_params={"project_name": cfg["name"]}
    prj = dr.Project.list(search_params=search_params)
    if len(prj) == 1:
        print("**** Find existing project **** ")
        project = prj[0]
    else:
        if argv.auto:
            print("**** Starting autopilot with '{}' target *****".format(cfg["target"]))
            project = dr.Project.start(
                project_name=cfg["name"],
                sourcedata=sourcedata,
                target=cfg["target"],
            )
            project.wait_for_autopilot()
            print("**** Auto Pilot Complete ****")
        else:
            project = dr.Project.create(sourcedata=sourcedata, project_name=cfg["name"])
            print("**** Starting Manual autopilot with '{}' target *****".format(cfg["target"]))
            project.analyze_and_model(target=cfg["target"], mode=dr.AUTOPILOT_MODE.MANUAL)
            blueprint = [bp for bp in project.get_blueprints() if bp.model_type == cfg["model_type"]][0]
            print("**** Training model type '{}' *****".format(cfg["model_type"]))
            project.train(blueprint)




    if argv.auto:
        print("**** Getting ModelRecommendation *****")
        model = dr.ModelRecommendation.get(project.id)
        model_id = model.model_id
    else:
        print("**** Getting model id *****")
        start_time = time.perf_counter()
        wait_sec = 120
        while True:
            if time.perf_counter() - start_time < wait_sec:
                model_list = project.get_models(
                    search_params={"name": cfg["model_type"]},
                    use_new_models_retrieval=False
                )
                if model_list:
                    model_id = model_list[0].id
                    break
            else:
                print("List of trained models returned empty after {} seconds".format(wait_sec))
                sys.exit(1)


    print("**** Project ID: {} **** ".format(project.id))
    deployments = dr.Deployment.list()
    deployment = False
    for d in deployments:
        if d.label == "{} deployment".format(cfg["name"]):
            print("**** found existing Deployment ****")
            deployment = d


    prediction_server = dr.PredictionServer.list()[0]
    model_name = "{}_registered_model_version".format(cfg["name"])
    if deployment == False:
        if argv.server:
            print("**** Create Deployment with Pred Server **** ")
            deployment = dr.Deployment.create_from_learning_model(
                model_id=model_id,
                label="{} deployment".format(cfg["name"]),
                description="Deployed with DataRobot client",
                prediction_environment_id=prediction_server.id,
            )
        else:

            reg_model = dr.RegisteredModel.list(search=model_name)
            if len(reg_model) == 0:
                print("**** Create Deployment with Serverless **** ")
                registered_model_version = dr.RegisteredModelVersion.create_for_leaderboard_item(
                    model_id=model_id,
                    name=model_name,
                    registered_model_name=model_name,
                )

            reg_model = dr.RegisteredModel.list(search=model_name)
            registered_model = dr.RegisteredModel.get(
                reg_model[0].id
            )
            registered_model_version = registered_model.list_versions()[0]


            # Wait for build to finish
            start_time = time.time()
            model_package_version = dr.RegisteredModel.get(
                    registered_model_version.registered_model_id
                ).get_version(registered_model_version.id)
            while model_package_version.build_status != "complete":
                print(f" Model package build status: {model_package_version.build_status}")
                model_package_version = dr.RegisteredModel.get(
                    registered_model_version.registered_model_id
                ).get_version(registered_model_version.id)
                time.sleep(5)
                if time.time() - start_time > 300:
                    print("Model package build did not complete in time, last observed: {model_package_version.build_status}")
                    sys.exit(1)

            # sys.exit(0)

            try:
                deployment = dr.Deployment.create_from_registered_model_version(
                    registered_model_version.id,
                    label="{} deployment".format(cfg["name"]),
                    description='serverless deployment',
                    prediction_environment_id=dr.PredictionEnvironment.list()[1].id, # 'Serverless Compute'
                )
            except dr.errors.ClientError as e:
                print("Error: {}".format(e))

    # Step 3: Make predictions
    lst = []
    r = requests.get(cfg["url"], allow_redirects=True,verify=not(argv.insecure))
    f = StringIO(r.text)
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

    for x in range(int(argv.total)):
        print("Sending requests {}/{}".format((x + 1), argv.total))
        predictions = requests.post(
            "https://{}/predApi/v1.0/deployments/{}/predictions".format(base_url, deployment.id),
            headers=prediction_headers,
            data=json.dumps(lst),
            verify=not(argv.insecure),
        )
        # print(predictions.text)
        if predictions.status_code != 200:
            print (" - ERROR on prediction got HTTP :{}".format(predictions.status_code))

    # Step 4: Monitor deployment
    service_stats = deployment.get_service_stats()
    print("**** Deployment Stats ****")
    pprint(service_stats.metrics)
    if service_stats.metrics.get("totalRequests", 0) == 0:
        print(" !!!! WARNING !!!! is not working as planned")

    if argv.clean:
        print("cleanup")
        print(" deleting deployment")
        deployment.delete()
        if not argv.server:
            print(" deleting RegisteredModel " + registered_model_version.registered_model_id)
            requests.delete(
                "https://{}/registeredModels/{}/".format(os.environ["DATAROBOT_ENDPOINT"], registered_model_version.registered_model_id),
                headers={
                    "Authorization": "Bearer {}".format(os.environ["DATAROBOT_API_TOKEN"]),
                    "Content-Type": "application/json",
                },
                verify=not(argv.insecure),
            )


        # print(" deleting project")
        # project.delete()

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-c", "--clean", action="store_true", default=False)
    p.add_option("--auto", action="store_true", default=False)
    p.add_option("--server", action="store_true", default=False)
    p.add_option("--upload", action="store_true", default=False)
    p.add_option("-n", "--ns", default="dr-app-charts-master-daily")
    p.add_option("-u", "--url", default="")
    p.add_option("-a", "--apikey", default="")
    p.add_option("-t", "--total", default=10)
    p.add_option("-i","--insecure", action="store_true", default=False)
    options, arguments = p.parse_args()
    start_time = datetime.now()
    main(options)
    end_time = datetime.now()
    print("Duration: {}".format(end_time - start_time))
