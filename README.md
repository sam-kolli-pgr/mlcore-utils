# Working with Stratos

Getting an model/pipeline upand running in Stratos involves the following steps:

1. Build an Image to be Run
2. Deploy the built image via ArgoCD
3. Create another ArgoCD application for "alias" functionality
4. Create another ArgoCD application for "namespace" (team)

## What does Blacklodge provide

1. Ability to wrap around a basic python repo and transform it into a Python Flask App or a Kafka App etc.
2. Logging
3. 


## Building an Image to be run

In Blacklodge, we wrap our functionality over a customer's (python) repo. An example of Blacklodge's offering is where we take a barebones python app and then tranform it into a Flask Application. Towards this, we have a repo called [blacklodge_containers](https://github.com/PCDST/blacklodge_containers) which contains the Dockerfiles and Python code for different functionality offered by Blacklodge.

For this, when we build a docker image (using a docker file from that repo), we embed the python code from the repo (that we are wrapping around) into the docker image being built. We take the information around customer's git repo and use it when we build the image. For building the image, we use the `containerbuild` end point from Stratos. This endpoint, takes in the following information:


    repository: str = field() # `pcdst/blacklodge_containers`
    git_branch: str = field() # typically `main`. this shud be the branch which has the wrapping functionality that we want to offer
    git_commit_sha: str = field() # the actual commit sha at the time of running
    image_name: str = field() # 
    dockerfile_path: str = field()
    docker_context: str = field()
    namespace: str = field()
    image_tags: List[str] = field(factory=list)
    injected_aws_role_arn: str = field()
    injected_aws_account_short_alias: str = field()
    registries: List[str] = field(factory=list)
    build_args: Dict[str, str] = field(factory=dict)
    git_fetch_depth: int = field(default=1)

The git related information above should be for the [blacklodge_containers](https://github.com/PCDST/blacklodge_containers) repo. The docker related information should be around the paths of the docker related files present in that repo. 

This built image is later pulled by k8s pod when we deploy. For a successfull deploy, the below (non exhaustive list) has to be true:

1. The path to which the docker image is tagged and pushed to should match the oath that is supplied to the helm chart when deploying hte model
2. The built image has the neccessary env vars required by the code. Some of the env vars are pushed when building, while some are pushed during deployment. We should be careful around supplying all the env vars that are needed at these two different phases. While the stratos infra might inject some env vars, we should gather a list of what stratos provides + what we provide at build time + what we provide at deploy time
3. The sidecar containers are also referenced properly and are available to be pulled

