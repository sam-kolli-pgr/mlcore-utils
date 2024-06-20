from abc import ABC, abstractmethod
import base64
from enum import Enum
import yaml
import json
from result import Err, Ok, Result, is_ok, is_err
import time
import ast
import requests
from typing import List, Optional, Tuple, Any, Dict
from attrs import define, field, asdict

from mlcore_utils.model.common import (
    Http_Method,
    Runtime_Environment,
    Runtime_Environment_Detector,
    Secret_Getter,
    Blacklodge_Action_Status,
)
from mlcore_utils.model.blacklodge import (
    Blacklodge_Model,
    Blacklodge_BusinessUnit,
    Blacklodge_Model_Type,
    Blacklodge_User,
    Pipeline_Alias,
)
from mlcore_utils.model.aws import AWS_Accounts_For_Blacklodge


class ArgoCD_Api_Caller(object):
    def __init__(
        self,
        secret_getter: Secret_Getter,
        version: int = 1,
        number_of_retries: int = 3,
        max_timeout: int = 30,
    ):
        self.secret_getter = secret_getter
        self.number_of_retries = number_of_retries
        self.max_timeout = max_timeout
        self.argocd_url = f"https://argocd.mgmt.stratos.prci.com/api/v{version}"

    def get_default_headers(self):
        secret_result = self.secret_getter.get_secret()
        if is_ok(secret_result):
            return {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {secret_result.ok_value.get_secret_value()}",
            }
        elif is_err(secret_result):
            raise Exception(
                "error getting secret for strator API: " + secret_result.err_value
            )
        else:
            raise Exception("Unknown error getting secret for Stratos API")

    def call_api(
        self,
        http_method: Http_Method,
        endpoint: str,
        json_data=None,
        timeout: int = 15,
        current_attempt_count: int = 1,
        max_number_of_attempts: int = 3,
        params=None,
    ) -> requests.Response:
        if (
            current_attempt_count <= max_number_of_attempts
            if max_number_of_attempts
            else self.number_of_retries
        ):
            try:
                url = f"{self.argocd_url}/{endpoint}"
                if http_method == Http_Method.POST:
                    response = requests.post(
                        url=url,
                        json=json_data,
                        headers=self.get_default_headers(),
                        timeout=timeout,
                        # verify="/etc/ssl/certs/ca-certificates.crt",
                    )
                    return response
                elif http_method == Http_Method.GET:
                    response = requests.get(
                        url=url,
                        json=json_data,
                        params=params,
                        headers=self.get_default_headers(),
                    )
                    return response
                else:
                    raise Exception(
                        "No implementation for http_method " + http_method.value
                    )
            except requests.exceptions.ReadTimeout:
                return self.call_api(
                    http_method,
                    endpoint,
                    json_data,
                    timeout,
                    current_attempt_count + 1,
                    max_number_of_attempts,
                )
        else:
            raise Exception(
                f"Could not reach endpoint {endpoint} after {max_number_of_attempts} attempts"
            )

    def call_status_url_and_await(self, status_response_url):
        finished = False
        seconds_to_wait = 60
        num_attempt = 0
        while not (finished or num_attempt > 30):
            status_response = self.call_api(
                http_method=Http_Method.GET,
                endpoint=f"{status_response_url}",
            )
            if status_response.status_code == 200:
                status = status_response.json()["status"]["health"]["status"]
                print("Current status " + status)
                if status.lower() == "healthy":
                    finished = True
                    return status_response
                else:
                    time.sleep(seconds_to_wait)
                    num_attempt = num_attempt + 1
            else:
                time.sleep(seconds_to_wait)
                num_attempt = num_attempt + 1

        if not finished:
            raise TimeoutError(
                f"Could not get status from {status_response_url} after {num_attempt * seconds_to_wait} seconds"
            )


class Stratos_Api_Caller(object):
    def __init__(
        self,
        secret_getter: Secret_Getter,
        version: int = 1,
        number_of_retries=3,
        max_timeout: int = 30,
    ) -> None:
        self.secret_getter = secret_getter
        self.number_of_retries = number_of_retries
        self.stratos_url = (
            f"https://jetstreamapi.apps.stratos.prci.com/api/v{version}/stratos"
        )
        self.max_timeout = max_timeout

    def get_default_stratos_headers(self):
        secret_result = self.secret_getter.get_secret()
        if is_ok(secret_result):
            return {
                "accept": "application/json",
                "access_token": secret_result.ok_value.get_secret_value(),
                "Content-Type": "application/json",
            }
        elif is_err(secret_result):
            raise Exception(
                "error getting secret for strator API: " + secret_result.err_value
            )
        else:
            raise Exception("Unknown error getting secret for Stratos API")

    def call_api(
        self,
        http_method: Http_Method,
        endpoint: str,
        json_data=None,
        timeout: int = 15,
        current_attempt_count: int = 1,
        max_number_of_attempts: int = 3,
        params=None,
    ):
        if (
            current_attempt_count <= max_number_of_attempts
            if max_number_of_attempts
            else self.number_of_retries
        ):
            try:
                url = f"{self.stratos_url}/{endpoint}"
                if http_method == Http_Method.POST:
                    response = requests.post(
                        url=url,
                        json=json_data,
                        headers=self.get_default_stratos_headers(),
                        timeout=timeout,
                        # verify="/etc/ssl/certs/ca-certificates.crt",
                    )
                    return response
                elif http_method == Http_Method.GET:
                    response = requests.get(
                        url=url,
                        json=json_data,
                        params=params,
                        headers=self.get_default_stratos_headers(),
                        timeout=timeout,
                        # verify="/etc/ssl/certs/ca-certificates.crt",
                    )
                    return response
                else:
                    raise Exception(
                        "No implementation for http_method " + http_method.value
                    )
            except requests.exceptions.ReadTimeout:
                return self.call_api(
                    http_method,
                    endpoint,
                    json_data,
                    timeout,
                    current_attempt_count + 1,
                    max_number_of_attempts,
                )
            except Exception as e:
                # should we do something else?
                raise e
        else:
            raise Exception(
                f"Could not reach endpoint {endpoint} after {max_number_of_attempts} attempts"
            )

    def call_status_url_and_await(self, status_response_url):
        finished = False
        seconds_to_wait = 60
        num_attempt = 0
        while not (finished or num_attempt > 30):
            # status_response = requests.get(url = f"{self.stratos_url}\\{status_response_url}", headers = self.get_default_stratos_headers())
            status_response = self.call_api(
                http_method=Http_Method.GET,
                endpoint=f"{status_response_url}",
            )
            if status_response.status_code == 200:
                status = status_response.json()["build_status"]
                print("Current status " + status)
                if status.lower() == "completed":
                    conclusion = (
                        status_response.json()["conclusion"]
                        if "conclusion" in status_response.json()
                        else "..."
                    )
                    print("finished with " + conclusion)
                    finished = True
                    return status_response
                else:
                    time.sleep(seconds_to_wait)
                    num_attempt = num_attempt + 1
            else:
                time.sleep(seconds_to_wait)
                num_attempt = num_attempt + 1

        if not finished:
            raise TimeoutError(
                f"Could not get status from {status_response_url} after {num_attempt * seconds_to_wait} seconds"
            )

    def call_api_and_await_status(
        self,
        http_method: Http_Method,
        url: str,
        json_data,
        status_for_action: str,
        keyword_status_is_based_on: str,
        timeout: int = 15,
        backoff: int = 0,
    ) -> Tuple[requests.Response, Optional[requests.Response]]:
        response = self.call_api(http_method, url, json_data, timeout, backoff)
        if response.status_code == 200:
            status_keyword_value = response.json()[keyword_status_is_based_on]
            status_response_url = (
                f"{status_for_action}/{status_keyword_value}/run-status"
            )
            return (response, self.call_status_url_and_await(status_response_url))
        else:
            return (response, None)


@define
class Stratos_Response_Wrapper(ABC):
    status: Blacklodge_Action_Status = field()
    message: Optional[Dict[str, Any]] = field()
    error: Optional[Dict[str, Any]] = field()


class Container_Builder(object):
    def __init__(self) -> None:
        pass

    @abstractmethod
    def build_container_image(self) -> Stratos_Response_Wrapper:
        pass


class Container_Build_Data_For_Stratos_Api_V1(object):
    def __init__(
        self,
        blacklodge_model: Blacklodge_Model,
        aws_metadata: AWS_Accounts_For_Blacklodge,
        blacklodge_business_unit: Blacklodge_BusinessUnit,
    ):
        self.blacklodge_model: Blacklodge_Model = blacklodge_model
        self.aws_metadata = aws_metadata
        self.blacklodge_business_unit = blacklodge_business_unit

    def get_docker_file_path(self):
        container = (
            self.blacklodge_model.runtime_config.blacklodge_container.prebuilt_container.get_prebuilt_container()
        )
        dockerfile_path = f"./dockerfiles/{container}/Dockerfile"
        return dockerfile_path

    def get_git_branch(self):
        # self.blacklodge_model.runtime_config.
        # git_branch = f"tag/{self.base_container_version}"
        # git_branch = f"tag/{self.blacklodge_model. base_container_version}"
        git_branch = "main"
        return git_branch

    def get_repository(self):
        org = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.github_organization.value
        )
        repo = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.git_repo_name
        )
        return f"{org.upper() if org == 'pcdst' else org}/{repo}"

    def get_docker_context(self):
        ctx = self.blacklodge_model.runtime_config.blacklodge_container.context_path
        return ctx

    def get_image_name(self):
        return f"blacklodge-{self.blacklodge_model.object_type.value}-{self.blacklodge_model.name}"

    def get_image_tags(self):
        return [self.blacklodge_model.version]

    def get_git_commit_sha(self):
        res = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.get_commit_sha()
        )
        if is_ok(res):
            return res.ok_value
        elif is_err(res):
            raise Exception("Error getting git commit sha " + res.err_value)
        else:
            raise Exception("Unknown error while getting git commit sha")

    def get_namespace(self):
        return self.blacklodge_business_unit.get_namespace()

    def get_injected_aws_role_arn(self):
        return "arn:aws:iam::004782836026:role/k8s-sa-mlcore-tgw-kaniko_build"

    def get_injected_aws_account_short_alias(self):
        return "aws0gd"

    def get_build_args(self):
        # default_env_vars = {"envvars": {"some_key": "some_value"}}
        # build_args = ast.literal_eval(self.blacklodge_model.runtime_config.inputs.strip("\n").strip(" ")) if self.blacklodge_model.runtime_config.inputs else default_env_vars
        build_args = {}
        build_args["PIPELINE_NAME"] = self.blacklodge_model.name
        build_args["PIPELINE_VERSION"] = str(self.blacklodge_model.version)
        build_args["APP_TYPE"] = self.blacklodge_model.object_type.value
        build_args["AWS_ACCOUNT_NUM"] = self.aws_metadata.aws_account_num
        build_args["PYTHON_VERSION"] = self.blacklodge_model.python_version
        # if self.linux_template:
        #    build_args["LINUX_TEMPLATE"] = self.linux_template
        return build_args


class Stratos_Api_V1_Container_Builder(Container_Builder):
    def __init__(
        self,
        container_build_data_for_stratos_api: Container_Build_Data_For_Stratos_Api_V1,
        stratos_api_caller: Stratos_Api_Caller,
        stratos_endpoint: str = "containerbuild",
    ) -> None:
        super().__init__()
        self.stratos_endpoint = stratos_endpoint
        self.data = container_build_data_for_stratos_api
        self.stratos_api_caller = stratos_api_caller

    def get_stratos_endpoint(self):
        return (
            "https://jetstreamapi.apps.stratos.prci.com/api/v1/stratos/containerbuild"
        )

    def build_container_image(self) -> Stratos_Response_Wrapper:
        js_build_body = {
            "repository": self.data.get_repository(),
            "dockerfile_path": self.data.get_docker_file_path(),
            "docker_context": self.data.get_docker_context(),
            "image_name": self.data.get_image_name(),
            "image_tags": self.data.get_image_tags(),
            "build_args": self.data.get_build_args(),
            "git_branch": self.data.get_git_branch(),
            "git_commit_sha": self.data.get_git_commit_sha(),
            "namespace": self.data.get_namespace(),
            "injected_aws_role_arn": self.data.get_injected_aws_role_arn(),
            "injected_aws_account_short_alias": self.data.get_injected_aws_account_short_alias(),
        }

        call_response: Tuple[requests.Response, Optional[requests.Response]] = (
            self.stratos_api_caller.call_api_and_await_status(
                http_method=Http_Method.POST,
                url=self.stratos_endpoint,
                json_data=js_build_body,
                status_for_action="containerbuild",
                keyword_status_is_based_on="commit_sha",
            )
        )

        if call_response[0].status_code == 200:
            if call_response[1]:
                if call_response[1].status_code == 200:
                    conclusion = call_response[1].json()["conclusion"]
                    if conclusion == "success":
                        return Stratos_Response_Wrapper(
                            status=Blacklodge_Action_Status.SUCCESS,
                            message=call_response[1].json(),
                            error=None,
                        )

                    else:
                        return Stratos_Response_Wrapper(
                            status=Blacklodge_Action_Status.FAILED,
                            message=None,
                            # error=f"Container Image Built priocess failed. YOu can find details here: <{call_response[1].json()['html_url']}>",
                            error=call_response[1].json(),
                        )

                else:
                    return Stratos_Response_Wrapper(
                        status=Blacklodge_Action_Status.FAILED,
                        message=None,
                        # error=call_response[1].text,
                        error={
                            "status_code": call_response[1].status_code,
                            "error": "request to build image successfulyl submitted. But process failed with error : "
                            + call_response[1].text,
                        },
                    )
            else:
                return Stratos_Response_Wrapper(
                    status=Blacklodge_Action_Status.UNKNOWN,
                    message=None,
                    error={
                        "error": "Container image built request successfully submitted, but could not get status of the action"
                    },
                )
        else:
            return Stratos_Response_Wrapper(
                status=Blacklodge_Action_Status.FAILED,
                message=None,
                error={
                    "status_code": call_response[0].status_code,
                    "error": "request to build image failed with error: "
                    + call_response[0].text,
                },
            )


class Blacklodge_Helm_Chart_Type(str, Enum):
    NAMESPACE = "blacklodge-namespace-resources"
    ALIAS = "blacklodge-user-alias"
    CRONJOB = "blacklodge-user-cronjob"
    JOB = "blacklodge-user-job"
    PIPELINE = "blacklodge-user-pipeline"


@define
class Stratos_Application_Values(object):
    platform: str = field(default="eds")
    account_id: str = field(default="1111111")
    allowed_cluster_types: List[str] = field(default=["blacklodge"])
    environment: str = field(init=False)
    helm_repositry: str = field(
        default="oci://867531445002.dkr.ecr.us-east-1.amazonaws.com/internal/helm/eds/blacklodge"
    )

    def __attrs_post_init__(self):
        runtime_env = Runtime_Environment_Detector.detect()
        if (
            runtime_env == Runtime_Environment.CLOUD9
            or runtime_env == Runtime_Environment.LOCAL_DOCKER
            or runtime_env == Runtime_Environment.LOCAL_MAC
        ):
            self.environment = "nonprod"
        elif runtime_env == Runtime_Environment.STRATOS:
            self.environment = "prod"

    def get_project_identifier(self, blacklodge_user: Blacklodge_User):
        return blacklodge_user.get_teamname()

    def get_mnamespace_identifier(self, blacklodge_user: Blacklodge_User):
        return blacklodge_user.get_teamname()

    def get_application_name(
        self,
        blacklodge_model: Blacklodge_Model,
        helm_chart_type: Blacklodge_Helm_Chart_Type,
    ):
        if helm_chart_type == Blacklodge_Helm_Chart_Type.PIPELINE:
            return f"{blacklodge_model.name}-{blacklodge_model.version}"
        elif helm_chart_type == Blacklodge_Helm_Chart_Type.ALIAS:
            alias_name = blacklodge_model.aliases[0].alias
            return f"{blacklodge_model.name}-{alias_name}"

    def get_platform(self):
        return self.platform

    def get_environment(self):
        return self.environment


class Stratos_Application_Values_ForAlias(object):
    platform: str = field(default="eds")
    account_id: str = field(default="1111111")
    allowed_cluster_types: List[str] = field(default=["blacklodge"])
    environment: str = field(init=False)
    helm_repositry: str = field(
        default="oci://867531445002.dkr.ecr.us-east-1.amazonaws.com/internal/helm/eds/blacklodge"
    )

    def __attrs_post_init__(self):
        runtime_env = Runtime_Environment_Detector.detect()
        if (
            runtime_env == Runtime_Environment.CLOUD9
            or runtime_env == Runtime_Environment.LOCAL_DOCKER
            or runtime_env == Runtime_Environment.LOCAL_MAC
        ):
            self.environment = "nonprod"
        elif runtime_env == Runtime_Environment.STRATOS:
            self.environment = "prod"

    def get_project_identifier(self, blacklodge_user: Blacklodge_User):
        return blacklodge_user.get_teamname()

    def get_mnamespace_identifier(self, blacklodge_user: Blacklodge_User):
        return blacklodge_user.get_teamname()

    def get_application_name(self, blacklodge_model: Blacklodge_Model):
        return f"{blacklodge_model.name}-kollialias"

    def get_platform(self):
        return self.platform

    def get_environment(self):
        return self.environment


class ArgoCD_Util(object):
    def __init__(
        self,
        stratos_application_values: Stratos_Application_Values,
        argocd_api_caller: ArgoCD_Api_Caller,
    ):
        self.stratos_application_values = stratos_application_values
        self.api_caller = argocd_api_caller

    def _get_cluster_id_from_response(
        self, response: requests.Response, cluster_type: str, environment: str
    ) -> Optional[str]:
        for cluster in response.json()["items"]:
            if (
                cluster["labels"]["stratos.progressive.com/cluster-type"]
                == cluster_type
                and cluster["labels"]["stratos.progressive.com/env"] == environment
            ):
                cluster_id = cluster["labels"]["stratos.progressive.com/cluster-id"]
                return cluster_id

    def get_cluster_id(self, cluster_type: str, environment: str) -> Result[str, str]:
        api_response: requests.Response = self.api_caller.call_api(
            Http_Method.GET, "clusters"
        )
        cluster_id = None
        if api_response.status_code == 200:
            cluster_id = self._get_cluster_id_from_response(
                api_response, cluster_type, environment
            )
        else:
            return Err(
                f"Could not get Cluster-Id from ArgoCD. Api response failed with status_code {api_response.status_code} and error {api_response.text}"
            )

        if cluster_id:
            return Ok(cluster_id)
        else:
            return Err(
                f"Could not get Cluster Id from Argo for cluster-type {cluster_type} in environment {environment}"
            )

    def get_argocd_application_name(
        self,
        blacklodge_model: Blacklodge_Model,
        blacklodge_user: Blacklodge_User,
        cluster_id: str,
    ):
        return f"{self.stratos_application_values.platform}-{self.stratos_application_values.get_project_identifier(blacklodge_user)}-{blacklodge_model.name}-{blacklodge_model.version}-{self.stratos_application_values.environment}-helm-{cluster_id}"

    def argocd_application_name(
        self,
        blacklodge_model: Blacklodge_Model,
        blacklodge_user: Blacklodge_User,
        stratos_api_caller: Stratos_Api_Caller,
    ):
        endpoint = "argocd/app-urls"
        data = {
            "platform": self.stratos_application_values.platform,
            "application_name": f"{blacklodge_model.name}-{blacklodge_model.version}",
            "environment_name": self.stratos_application_values.environment,
            "project_identifier": self.stratos_application_values.get_project_identifier(
                blacklodge_user
            ),
        }
        response = stratos_api_caller.call_api(
            http_method=Http_Method.GET, endpoint=endpoint, json_data=data
        )
        if response.status_code == 200:
            return response.json()[0]["name"]
        else:
            raise Exception(f"Could not get argocd app name for {data}")

    def get_application_status_a(
        self,
        blacklodge_model: Blacklodge_Model,
        blacklodge_user: Blacklodge_User,
        cluster_id: str,
    ):
        argocd_application_name = self.get_argocd_application_name(
            blacklodge_model, blacklodge_user, cluster_id
        )
        tail_lines = 500
        endpoint = "eds-bl-test-ap-14-nonprod-helm-n51e1/resource/links?name=bl-test-ap-14-cf8dfc46f-ffcwn&appNamespace=argocd&namespace=eds-cla-cc-nonprod&resourceName=bl-test-ap-14-cf8dfc46f-ffcwn&version=v1&kind=Pod&group="
        endpoint = "eds-bl-test-ap-14-nonprod-helm-n51e1/resource?name=bl-test-ap-14-cf8dfc46f-ffcwn&appNamespace=argocd&kind=Pod&version=v1&resourceName=bl-test-ap-14-cf8dfc46f-ffcwn&namespace=eds-cla-cc-nonprod"
        # endpoint="eds-bl-test-ap-14-nonprod-helm-n51e1/resource?name=bl-test-ap-14-cf8dfc46f-ffcwn&appNamespace=argocd&kind=Pod&version=v1&resourceName=bl-test-ap-14-cf8dfc46f-ffcwn&namespace=eds-cla-cc-nonprod"
        endpoint = f"{argocd_application_name}/logs?tail_lines={tail_lines}&container=bl-test-ap-14"
        api_response = self.api_caller.call_api(
            Http_Method.GET, f"applications/{endpoint}"
        )
        if api_response.status_code == 200:
            print(api_response.text)
            # for key in api_response.json():
            #    print(key)
            #    #print(api_response.json()[key])
            #    for k in api_response.json()[key]:
            #        print(k)
            #        print(api_response.json()[key][k])
            #    print("\n\n")
        else:
            print(api_response.status_code)
            print(api_response.text)

    def get_application_status(self):
        full_app_name = "eds-bl-test-ap-17-nonprod-helm-n51e1"
        api_response = self.api_caller.call_status_url_and_await(
            f"applications/{full_app_name}"
        )
        if api_response.status_code == 200:
            print(api_response.text)
            # for key in api_response.json():
            #    print(key)
            #    #print(api_response.json()[key])
            #    for k in api_response.json()[key]:
            #        print(k)
            #        print(api_response.json()[key][k])
            #    print("\n\n")
        else:
            print(api_response.status_code)
            print(api_response.text)


@define
class Splunk_Constants(object):
    environment: str = field(default="Development")


@define
class Container_Deploy_Data_For_Stratos_Api_V1(object):
    stratos_application_values: Stratos_Application_Values = field()
    aws_constants: AWS_Accounts_For_Blacklodge = field()
    splunk_constants: Splunk_Constants = field()
    blacklodge_model: Blacklodge_Model = field()
    blacklodge_user: Blacklodge_User = field()
    blacklodge_helm_chart_type: Blacklodge_Helm_Chart_Type = field()
    chart_version: str = field(default="0.3.25")
    bl_object: str = field(default="deployment")

    def get_stratos_application_name(self) -> str:
        return self.stratos_application_values.get_application_name(
            self.blacklodge_model, self.blacklodge_helm_chart_type
        )

    def get_stratos_namespace_name(
        self,
    ):
        return self.stratos_application_values.get_mnamespace_identifier(
            self.blacklodge_user
        )

    def get_stratos_platform(self) -> str:
        return self.stratos_application_values.get_platform()

    def get_stratos_environment(self) -> str:
        return self.stratos_application_values.get_environment()

    def get_stratos_project_identifier(self) -> str:
        return self.stratos_application_values.get_project_identifier(
            self.blacklodge_user
        )

    def get_stratos_account_id(self) -> str:
        return self.stratos_application_values.account_id

    def get_stratos_cluster_type(self) -> str:
        return self.stratos_application_values.allowed_cluster_types[0]

    def get_stratos_repository(self) -> str:
        return self.blacklodge_model.git_repo.git_repo_name

    def get_stratos_repository_url(self) -> str:
        return self.blacklodge_model.git_repo.git_repo_url

    def get_stratos_application_contact(self) -> str:
        return self.blacklodge_model.user_email[0]

    def get_chart_yaml_contents(self):
        # if self.bl_object == "deployment":
        #    chart_yaml = self._generate_chart_yaml()
        # else:
        #    chart_yaml = self._generate_alias_chart_yaml()
        chart_yaml = self._generate_chart_yaml()
        return base64.urlsafe_b64encode(chart_yaml.encode()).decode()

    def get_value_yaml_contents(self):
        # if self.bl_object == "deployment":
        #    values_yaml = self._generate_values_yaml()
        # else:
        #    values_yaml = self._generate_alias_values_yaml()
        values_yaml = self._generate_values_yaml()
        return base64.urlsafe_b64encode(values_yaml.encode()).decode()

    def _generate_alias_values_yaml(self) -> str:
        """
        Generates a helm values.yaml string from the provided inputs
        """

        values_yaml_dict = {
            f"blacklodge-user-alias": {
                "modelName": f"{self.blacklodge_model.name}",
                "modelVersion": self.blacklodge_model.version,
                "aliasName": "kollialias",
                "environment": self.stratos_application_values.environment,
                "modelPort": 8081,
            }
        }
        return yaml.dump(values_yaml_dict)

    def _generate_alias_chart_yaml(self) -> str:
        """
        Generates an appropriate helm Chart.yaml string that uses our pre-built templates
        """

        dependencies_list = [
            {
                "name": f"blacklodge-user-alias",
                "version": "0.2.4",
                "repository": "oci://867531445002.dkr.ecr.us-east-1.amazonaws.com/internal/helm/eds/blacklodge",
            }
        ]

        chart_dict = {
            "apiVersion": "v2",
            "name": f"blacklodge-{self.blacklodge_model.name}-alias",
            "description": "chart defn 2",
            "type": "application",
            "version": "1.0.0",
            "appVersion": f"{self.blacklodge_model.version}.0.0",
            "dependencies": dependencies_list,
        }
        return yaml.dump(chart_dict)

    def _generate_values_yaml(self) -> str:
        """
        Generates a helm values.yaml string from the provided inputs
        """
        namespace = self.blacklodge_user.get_teamname()

        ## Generating yaml file for helm values
        image_dict = {
            # "path": self.aws_constants.get_ecr_image_path(
            #    self.stratos_application_values.platform,
            #    namespace,
            #    self.blacklodge_model.object_type.value,
            #    self.blacklodge_model.name,
            #    self.blacklodge_model.version,
            # )
            "path": self.blacklodge_model.get_ecr_image_path(
                self.aws_constants, self.stratos_application_values.platform, namespace
            )
        }

        resources_dict = {
            "limits": {
                "cpu": str(self.blacklodge_model.runtime_config.max_cpu),
                "memory": f"{int(self.blacklodge_model.runtime_config.max_memory_mb)}M",
            },
            "requests": {
                "cpu": str(self.blacklodge_model.runtime_config.min_cpu),
                "memory": f"{int(self.blacklodge_model.runtime_config.min_memory_mb)}M",
            },
        }

        clean_environment = (
            "prod"
            if self.stratos_application_values.environment == "prod"
            else "nonprod"
        )

        host_list = [
            {
                "host": f"mlcore-{clean_environment}.apps.{clean_environment}.stratos.prci.com",
                "paths": [
                    {
                        "path": f"/v1/pipelines/{self.blacklodge_model.name}/versions/{self.blacklodge_model.version}",
                        "pathType": "Prefix",
                    }
                ],
            },
            # {
            #    "host": f"mlcore-{clean_environment}.apps.{clean_environment}.stratos.prci.com",
            #    "paths": [
            #        {
            #            "path": f"/v1/pipelines/{self.blacklodge_model.name}/versions/skollialias",
            #            "pathType": "Prefix",
            #        }
            #    ],
            # },
        ]

        ingress_dict = {"hosts": host_list}

        values_yaml_dict = {
            f"blacklodge-user-{self.blacklodge_model.object_type.value}": {
                "replicaCount": str(self.blacklodge_model.runtime_config.replicas),
                "fullnameOverride": f"{self.blacklodge_model.name}-{self.blacklodge_model.version}",
                "environment": self.stratos_application_values.environment,
                "splunk_environment": self.splunk_constants.environment,
                "containerName": f"{self.blacklodge_model.name}-{self.blacklodge_model.version}",
                "image": image_dict,
                "resources": resources_dict,
                "ingress": ingress_dict,
                "envvars": [],
            }
        }

        if self.blacklodge_model.runtime_config.minimum_replicas > 0:
            autoscaling_dict = {
                "enabled": True,
                "minReplicas": self.blacklodge_model.runtime_config.minimum_replicas,
                "maxReplicas": self.blacklodge_model.runtime_config.maximum_replicas,
                "targetCPUUtilizationPercentage": str(
                    self.blacklodge_model.runtime_config.target_cpu_utilization
                ),
                "targetMemoryUtilizationPercentage": str(
                    self.blacklodge_model.runtime_config.target_memory_utilization
                ),
            }
            values_yaml_dict[
                f"blacklodge-user-{self.blacklodge_model.object_type.value}"
            ]["autoscaling"] = autoscaling_dict

        if self.blacklodge_model.runtime_config.inputs:
            values_yaml_dict[
                f"blacklodge-user-{self.blacklodge_model.object_type.value}"
            ]["envvars"] = self.blacklodge_model.runtime_config.inputs

        ### OTEL Default variable
        values_yaml_dict[f"blacklodge-user-{self.blacklodge_model.object_type.value}"][
            "envvars"
        ].append(
            {
                "name": "OTEL_RESOURCE_ATTRIBUTES",
                "value": f"service.name=MLCore - {self.blacklodge_model.name}, service.namespace={namespace}, service.version={self.blacklodge_model.version}",
            }
        )

        if not self.blacklodge_model.runtime_config.otel_tracing:
            otel_dict = {"enabled": False}
            values_yaml_dict[
                f"blacklodge-user-{self.blacklodge_model.object_type.value}"
            ]["monitoring"] = {"otel": otel_dict}
            values_yaml_dict[
                f"blacklodge-user-{self.blacklodge_model.object_type.value}"
            ]["envvars"].append({"name": "OTEL_TRACES_SAMPLER", "value": "always_off"})

        else:
            values_yaml_dict[
                f"blacklodge-user-{self.blacklodge_model.object_type.value}"
            ]["envvars"].append({"name": "OTEL_TRACES_SAMPLER", "value": "always_on"})

        return yaml.dump(values_yaml_dict)

    def _generate_chart_yaml(self) -> str:
        """
        Generates an appropriate helm Chart.yaml string that uses our pre-built templates
        """

        ## TODO: Handle dependency versioning? Latest?
        dependencies_list = [
            {
                "name": f"blacklodge-user-{self.blacklodge_model.object_type.value}",
                "version": self.chart_version,
                "repository": self.stratos_application_values.helm_repositry,
            }
        ]

        chart_dict = {
            "apiVersion": "v2",
            "name": f"blacklodge-{self.blacklodge_model.object_type.value}-{self.blacklodge_model.name}",
            "description": "Auto-generated template for blacklodge deployment",
            "type": "application",
            "version": "1.0.0",
            "appVersion": f"{self.blacklodge_model.version}.0.0",
            "dependencies": dependencies_list,
        }

        return yaml.dump(chart_dict)


class Container_Deployer(object):

    def __init__(self) -> None:
        pass

    @abstractmethod
    def deploy_container_image(self) -> Stratos_Response_Wrapper:
        pass


@define
class Stratos_AppOwnersMetadata_V1(object):
    repository: str = field()
    repository_url: str = field()
    application_contact: str = field()
    application_name: str = field()
    platform: str = field(default="eds")
    allowed_cluster_types: List[str] = field(default=["blacklodge"])

    @classmethod
    def get_data_using_blacklodge_model(
        cls, blacklodge_model: Blacklodge_Model, application_name: str
    ):
        stratos_application_metadata = Stratos_AppOwnersMetadata_V1(
            repository=blacklodge_model.git_repo.git_repo_name,
            repository_url=blacklodge_model.git_repo.git_repo_url,
            application_contact=blacklodge_model.user_email[0],
            application_name=application_name,
        )
        return stratos_application_metadata


@define
class Stratos_ProjectMetadata_V1(object):
    environment_name: str = field()
    application_name: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    rendered_project_name: str = field(init=False)

    def __attrs_post_init__(self):
        self.rendered_project_name = (
            f"{self.platform}-{self.project_identifier}-{self.environment_name}"
        )


@define
class Stratos_NamespaceMetadata_V1(object):
    environment_name: str = field()
    application_name: str = field()
    namespace_identifier: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    is_dynamic_environment: bool = field(default=False)
    dynamic_environment_name: str = field(default="")
    account_id: str = field(default="111111")
    cluster_type: str = field(default="blacklodge")


@define
class Stratos_ContainerHelDeployRequest_V1(object):
    base64_chart_yaml_contents: str = field()
    base64_values_yaml_contents: str = field()
    environment_name: str = field()
    application_name: str = field()
    namespace_identifier: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    is_dynamic_environment: bool = field(default=False)
    dynamic_environment_name: str = field(default="")
    cluster_type: str = field(default="blacklodge")


@define
class Stratos_AppSyncArgoRequest_V1(object):
    environment_name: str = field()
    application_name: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    is_dynamic_environment: bool = field(default=False)
    dynamic_environment_name: str = field(default="")


@define
class Stratos_Api_V1_Util(object):
    stratos_api_caller: Stratos_Api_Caller = field()

    def deploy_helm_chart_and_values(
        self, helm_deploy_request: Stratos_ContainerHelDeployRequest_V1
    ) -> Result[bool, str]:
        endpoint = "containerdeploy/helm/chart_and_values_yaml"
        data = asdict(helm_deploy_request)
        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.POST,
                endpoint=endpoint,
                json_data=data,
            )
            if response.status_code == 200:
                return Ok(True)
            else:
                print(
                    f"Error while deploying helm data. Status_Code {response.status_code}. Text: {response.text}"
                )
                return Err(
                    f"Error while deploying helm data. Status_Code {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err(f"Error while trying to deploy helm data: " + str(e))

    def deploy_helm_chart(
        self, helm_deploy_request: Stratos_ContainerHelDeployRequest_V1
    ) -> Result[bool, str]:
        endpoint = "containerdeploy/helm/chart_yaml"
        print("Calling " + endpoint)
        data = {
            "platform": helm_deploy_request.platform,
            "application_name": helm_deploy_request.application_name,
            "environment_name": helm_deploy_request.environment_name,
            "project_identifier": helm_deploy_request.project_identifier,
            "is_dynamic_environment": False,
            "dynamic_environment_name": "",
            "base64_yaml_contents": helm_deploy_request.base64_chart_yaml_contents,
            "namespace_identifier": helm_deploy_request.namespace_identifier,
            "cluster_type": helm_deploy_request.cluster_type,
        }
        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.POST,
                endpoint=endpoint,
                json_data=data,
            )
            if response.status_code == 200:
                return Ok(True)
            else:
                print(
                    f"Error while deploying helm data. Status_Code {response.status_code}. Text: {response.text}"
                )
                return Err(
                    f"Error while deploying helm data. Status_Code {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err(f"Error while trying to deploy helm data: " + str(e))

    def sync_argocd_application(
        self,
        app_sync_request: Stratos_AppSyncArgoRequest_V1,
        stratos_call_success: bool = True,
        attempt=1,
    ):
        endpoint = "argocd/app-sync"
        data = asdict(app_sync_request)
        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.POST,
                endpoint=endpoint,
                json_data=data,
            )
            if response.status_code == 200:
                print("isssued successful sync call")
                return Ok(True)
            elif response.status_code == 500 and stratos_call_success and attempt <= 12:
                if (
                    "Could not find any ArgoCD Applications".lower()
                    in response.text.lower()
                ):
                    print("will check again in 60 seconds...")
                    time.sleep(60)
                    return self.sync_argocd_application(
                        app_sync_request, stratos_call_success, attempt + 1
                    )
                else:
                    print(
                        f"Error while syncing argocd capp. Status_Code {response.status_code}. Text: {response.text}"
                    )
                    return Err(
                        f"Error while syncing argocd capp. Status_Code {response.status_code}. Text: {response.text}"
                    )

            else:
                print(
                    f"Error while deploying helm data. Status_Code {response.status_code}. Text: {response.text}"
                )
                return Err(
                    f"Error while deploying helm data. Status_Code {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err(f"Error while trying to deploy helm data: " + str(e))

    def check_if_argocd_project_exists_using_stratos_sdk(
        self, project_metadata: Stratos_ProjectMetadata_V1
    ) -> Result[bool, str]:
        endpoint = f"argocd/projects"
        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.GET,
                endpoint=endpoint,
            )
            if response.status_code == 200:
                available_projects = response.json()
                return Ok(project_metadata.rendered_project_name in available_projects)
            else:
                print(
                    f"Error while trying to query ArgoCD project. Status_Code: {response.status_code}. Text: {response.text}"
                )
                return Err(
                    f"Error while trying to query ArgoCD project. Status_Code: {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err("Error while trying to query Stratos application " + str(e))

    def check_if_stratos_application_exists(
        self, appowners_metadata: Stratos_AppOwnersMetadata_V1
    ) -> Result[bool, str]:
        endpoint = f"containerdeploy/application-owner"
        json_data = {
            "platform": appowners_metadata.platform,
            "application_name": f"{appowners_metadata.application_name}",
        }
        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.GET,
                endpoint=endpoint,
                params=json_data,
            )
            if response.status_code == 200:
                return Ok(True)
            if response.status_code == 500:
                return Ok(False)
            else:
                return Err(
                    f"Error while trying to query Stratos Application. Status_Code: {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err("Error while trying to query Stratos application " + str(e))

    def _create_argocd_project_using_stratos_sdk(
        self, project_metadata: Stratos_ProjectMetadata_V1
    ) -> Result[bool, str]:
        endpoint = "argocd/projects"
        data = asdict(project_metadata)
        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.POST,
                endpoint=endpoint,
                json_data=data,
            )
            if response.status_code == 200:
                return Ok(True)
            else:
                print(
                    f"Error while creating ArgoCD Project {project_metadata.project_identifier}. Status_Code {response.status_code}. Text: {response.text}"
                )
                return Err(
                    f"Error while creating ArgoCD Project {project_metadata.project_identifier}. Status_Code {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err(
                f"Error while trying to create ArgoCD Project {project_metadata.project_identifier}: "
                + str(e)
            )

    def _create_k8s_namespace_using_stratos_sdk(
        self, namespace_metadata: Stratos_NamespaceMetadata_V1
    ) -> Result[bool, str]:
        endpoint = "argocd/namespace"
        data = asdict(namespace_metadata)
        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.POST,
                endpoint=endpoint,
                json_data=data,
            )
            if response.status_code == 200:
                return Ok(True)
            else:
                print(
                    f"Error while creating K8s Namespace. Status_Code {response.status_code}. Text: {response.text}"
                )
                return Err(
                    f"Error while creating K8s Namespace. Status_Code {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err(
                f"Error while trying to create K8s Namespace. {namespace_metadata.namespace_identifier}: "
                + str(e)
            )

    def _create_stratos_application(
        self, appowners_metadata: Stratos_AppOwnersMetadata_V1
    ) -> Result[bool, str]:
        endpoint = "argocd/app-owners"
        data = {
            "allowed_cluster_types": appowners_metadata.allowed_cluster_types,
            "repository": appowners_metadata.repository,
            "repository_url": appowners_metadata.repository_url,
            "application_contact": appowners_metadata.application_contact,
            "platform": appowners_metadata.platform,
            "application_name": appowners_metadata.application_name,
        }

        try:
            response = self.stratos_api_caller.call_api(
                http_method=Http_Method.POST,
                endpoint=endpoint,
                json_data=asdict(appowners_metadata),
            )
            if response.status_code == 200:
                return Ok(True)
            else:
                print(
                    f"Error while creating Stratos Application. Status_Code {response.status_code}. Text: {response.text}"
                )
                return Err(
                    f"Error while creating Stratos Application. Status_Code {response.status_code}. Text: {response.text}"
                )
        except Exception as e:
            return Err(
                f"Error while trying to create Stratos application {appowners_metadata.application_name}: "
                + str(e)
            )

    def create_k8s_namespace_using_stratos_sdk(
        self, namespace_metadata: Stratos_NamespaceMetadata_V1
    ) -> Result[bool, str]:
        namepsace_exists_result = Ok(False)
        if is_ok(namepsace_exists_result):
            namespace_exists = namepsace_exists_result.ok_value
            if namespace_exists:
                return Ok(True)
            else:
                return self._create_k8s_namespace_using_stratos_sdk(namespace_metadata)

    def create_argocd_project_using_stratos_sdk(
        self, project_metadata: Stratos_ProjectMetadata_V1
    ) -> Result[bool, str]:
        project_exists_result = self.check_if_argocd_project_exists_using_stratos_sdk(
            project_metadata
        )
        if is_ok(project_exists_result):
            project_exists = project_exists_result.ok_value
            if project_exists:
                return Ok(True)
            else:
                return self._create_argocd_project_using_stratos_sdk(project_metadata)

    def create_stratos_application(
        self, appowners_metadata: Stratos_AppOwnersMetadata_V1
    ) -> Result[bool, str]:
        app_exists_result = self.check_if_stratos_application_exists(appowners_metadata)
        if is_ok(app_exists_result):
            app_exists = app_exists_result.ok_value
            if app_exists:
                return Ok(True)
            else:
                return self._create_stratos_application(appowners_metadata)


@define
class Helm_Repo_Deployer(object):
    helm_chart_type: Blacklodge_Helm_Chart_Type = field()
    stratos_application_values: Stratos_Application_Values = field()
    aws_constants: AWS_Accounts_For_Blacklodge = field()
    splunk_constants: Splunk_Constants = field()

    def _get_chart_version(self):
        if self.helm_chart_type == Blacklodge_Helm_Chart_Type.PIPELINE:
            return "0.3.25"
        elif self.helm_chart_type == Blacklodge_Helm_Chart_Type.ALIAS:
            return "0.2.4"
        elif self.helm_chart_type == Blacklodge_Helm_Chart_Type.CRONJOB:
            return "0.2.3"
        elif self.helm_chart_type == Blacklodge_Helm_Chart_Type.JOB:
            return "0.2.4"
        elif self.helm_chart_type == Blacklodge_Helm_Chart_Type.NAMESPACE:
            return "0.1.1"

    def _get_dependencies_list(self):
        dependencies_list = [
            {
                "name": self.helm_chart_type.value,
                "version": self._get_chart_version(),
                "repository": self.stratos_application_values.helm_repositry,
            }
        ]
        return dependencies_list

    def _get_chart_content(self):
        chart_dict = {
            "apiVersion": "v2",
            "name": self.helm_chart_type.value,
            "description": f"Auto-generated template for {self.helm_chart_type.value}",
            "type": "application",
            "version": "1.0.0",
            "appVersion": "1.0.0",
            "dependencies": self._get_dependencies_list(),
        }
        return chart_dict

    def _get_values_content_for_pipeline(
        self, blacklodge_model: Blacklodge_Model, blacklodge_user: Blacklodge_User
    ):
        """
        Generates a helm values.yaml string from the provided inputs
        """
        namespace = blacklodge_user.get_teamname()

        ## Generating yaml file for helm values
        image_dict = {
            # "path": self.aws_constants.get_ecr_image_path(
            #    self.stratos_application_values.platform,
            #    namespace,
            #    blacklodge_model.object_type.value,
            #    blacklodge_model.name,
            #    blacklodge_model.version,
            # )
            "path": blacklodge_model.get_ecr_image_path(
                self.aws_constants, self.stratos_application_values.platform, namespace
            )
        }

        resources_dict = {
            "limits": {
                "cpu": str(blacklodge_model.runtime_config.max_cpu),
                "memory": f"{int(blacklodge_model.runtime_config.max_memory_mb)}M",
            },
            "requests": {
                "cpu": str(blacklodge_model.runtime_config.min_cpu),
                "memory": f"{int(blacklodge_model.runtime_config.min_memory_mb)}M",
            },
        }

        clean_environment = (
            "prod"
            if self.stratos_application_values.environment == "prod"
            else "nonprod"
        )

        host_list = [
            {
                "host": f"mlcore-{clean_environment}.apps.{clean_environment}.stratos.prci.com",
                "paths": [
                    {
                        "path": f"/v1/pipelines/{blacklodge_model.name}/versions/{blacklodge_model.version}",
                        "pathType": "Prefix",
                    }
                ],
            },
            # {
            #    "host": f"mlcore-{clean_environment}.apps.{clean_environment}.stratos.prci.com",
            #    "paths": [
            #        {
            #            "path": f"/v1/pipelines/{blacklodge_model.name}/versions/skollialias",
            #            "pathType": "Prefix",
            #        }
            #    ],
            # },
        ]

        ingress_dict = {"hosts": host_list}

        values_yaml_dict = {
            self.helm_chart_type.value: {
                "replicaCount": str(blacklodge_model.runtime_config.replicas),
                "fullnameOverride": f"{blacklodge_model.name}-{blacklodge_model.version}",
                "environment": self.stratos_application_values.environment,
                "splunk_environment": self.splunk_constants.environment,
                "containerName": f"{blacklodge_model.name}-{blacklodge_model.version}",
                "image": image_dict,
                "resources": resources_dict,
                "ingress": ingress_dict,
                "envvars": [],
            }
        }

        if blacklodge_model.runtime_config.minimum_replicas > 0:
            autoscaling_dict = {
                "enabled": True,
                "minReplicas": blacklodge_model.runtime_config.minimum_replicas,
                "maxReplicas": blacklodge_model.runtime_config.maximum_replicas,
                "targetCPUUtilizationPercentage": str(
                    blacklodge_model.runtime_config.target_cpu_utilization
                ),
                "targetMemoryUtilizationPercentage": str(
                    blacklodge_model.runtime_config.target_memory_utilization
                ),
            }
            values_yaml_dict[f"blacklodge-user-{blacklodge_model.object_type.value}"][
                "autoscaling"
            ] = autoscaling_dict

        if blacklodge_model.runtime_config.inputs:
            values_yaml_dict[self.helm_chart_type.value][
                "envvars"
            ] = blacklodge_model.runtime_config.inputs

        ### OTEL Default variable
        values_yaml_dict[self.helm_chart_type.value]["envvars"].append(
            {
                "name": "OTEL_RESOURCE_ATTRIBUTES",
                "value": f"service.name=MLCore - {blacklodge_model.name}, service.namespace={namespace}, service.version={blacklodge_model.version}",
            }
        )

        if not blacklodge_model.runtime_config.otel_tracing:
            otel_dict = {"enabled": False}
            values_yaml_dict[self.helm_chart_type.value]["monitoring"] = {
                "otel": otel_dict
            }
            values_yaml_dict[self.helm_chart_type.value]["envvars"].append(
                {"name": "OTEL_TRACES_SAMPLER", "value": "always_off"}
            )

        else:
            values_yaml_dict[self.helm_chart_type.value]["envvars"].append(
                {"name": "OTEL_TRACES_SAMPLER", "value": "always_on"}
            )

        return values_yaml_dict

    def _get_values_content_for_alias(self, model_name, pipeline_alias: Pipeline_Alias):
        """
        Generates a helm values.yaml string from the provided inputs
        """
        values_yaml_dict = {
            self.helm_chart_type.value: {
                "modelName": model_name,
                "modelVersion": pipeline_alias.version,
                "aliasName": pipeline_alias.alias,
                "environment": self.stratos_application_values.environment,
                "modelPort": 8081,
            }
        }
        return values_yaml_dict

    def _get_values_content_for_namespace(self):
        return None


@define
class Stratos_Deployer_Data_Interface(ABC):
    stratos_application_values: Stratos_Application_Values = field()

    @abstractmethod
    def get_stratos_application_name(self) -> str:
        pass

    @abstractmethod
    def get_stratos_namespace_name(
        self,
    ):
        pass

    def get_stratos_platform(self) -> str:
        return self.stratos_application_values.get_platform()

    def get_stratos_environment(self) -> str:
        return self.stratos_application_values.get_environment()

    @abstractmethod
    def get_stratos_project_identifier(self) -> str:
        pass

    def get_stratos_account_id(self) -> str:
        return self.stratos_application_values.account_id

    def get_stratos_cluster_type(self) -> str:
        return self.stratos_application_values.allowed_cluster_types[0]

    # @abstractmethod
    # def get_stratos_repository(self) -> str:
    #    pass

    # @abstractmethod
    # def get_stratos_repository_url(self) -> str:
    #    pass

    # @abstractmethod
    # def get_stratos_application_contact(self) -> str:
    #    return self.blacklodge_model.user_email[0]

    @abstractmethod
    def get_chart_yaml_contents(self):
        pass

    @abstractmethod
    def get_value_yaml_contents(self):
        pass

    def get_stratos_containerhelm_deployrequest_v1(
        self,
    ) -> Stratos_ContainerHelDeployRequest_V1:
        helm_data = Stratos_ContainerHelDeployRequest_V1(
            base64_chart_yaml_contents=self.data.get_chart_yaml_contents(),
            base64_values_yaml_contents=self.data.get_value_yaml_contents(),
            environment_name=self.data.get_stratos_environment(),
            application_name=self.data.get_stratos_application_name(),
            namespace_identifier=self.data.get_stratos_namespace_name(),
            project_identifier=self.data.get_stratos_project_identifier(),
        )
        return helm_data


@define
class Blacklodge_Pipeline_Deployer_Data(Stratos_Deployer_Data_Interface):
    stratos_application_values: Stratos_Application_Values = field()
    aws_constants: AWS_Accounts_For_Blacklodge = field()
    splunk_constants: Splunk_Constants = field()
    blacklodge_model: Blacklodge_Model = field()
    blacklodge_user: Blacklodge_User = field()
    helm_chart: Helm_Repo_Deployer = field(init=False)

    def __attrs_post_init__(self):
        helm_chart_type = Blacklodge_Helm_Chart_Type.PIPELINE
        self.helm_chart = Helm_Repo_Deployer(
            helm_chart_type=helm_chart_type,
            stratos_application_values=self.stratos_application_values,
            aws_constants=self.aws_constants,
            splunk_constants=self.splunk_constants,
        )

    def get_stratos_application_name(self) -> str:
        return f"{self.blacklodge_model.name}-{self.blacklodge_model.version}"

    def get_stratos_namespace_name(
        self,
    ):
        return self.blacklodge_user.get_namespace()

    def get_stratos_project_identifier(self) -> str:
        return self.blacklodge_user.get_teamname()

    def get_chart_yaml_contents(self):
        chart_content = self.helm_chart._get_chart_content()
        chart_yaml = yaml.dump(chart_content)
        return base64.urlsafe_b64encode(chart_yaml.encode()).decode()

    def get_value_yaml_contents(self):
        value_content = self.helm_chart._get_values_content_for_pipeline(
            self.blacklodge_model, self.blacklodge_user
        )
        value_yaml = yaml.dump(value_content)
        return base64.urlsafe_b64encode(value_yaml.encode()).decode()


@define
class Blacklodge_Alias_Deployer_Data(Stratos_Deployer_Data_Interface):
    stratos_application_values: Stratos_Application_Values = field()
    aws_constants: AWS_Accounts_For_Blacklodge = field()
    splunk_constants: Splunk_Constants = field()
    blacklodge_model: Blacklodge_Model = field()
    pipeline_alias: Pipeline_Alias = field()
    blacklodge_user: Blacklodge_User = field()
    helm_chart: Helm_Repo_Deployer = field(init=False)

    def __attrs_post_init__(self):
        helm_chart_type = Blacklodge_Helm_Chart_Type.ALIAS
        self.helm_chart = Helm_Repo_Deployer(
            helm_chart_type=helm_chart_type,
            stratos_application_values=self.stratos_application_values,
            aws_constants=self.aws_constants,
            splunk_constants=self.splunk_constants,
        )

    def get_stratos_application_name(self) -> str:
        return f"{self.blacklodge_model.name}-{self.pipeline_alias.alias}"

    def get_stratos_namespace_name(
        self,
    ):
        return self.blacklodge_user.get_namespace()

    def get_stratos_project_identifier(self) -> str:
        return self.blacklodge_user.get_teamname()

    def get_chart_yaml_contents(self):
        chart_content = self.helm_chart._get_chart_content()
        chart_yaml = yaml.dump(chart_content)
        return base64.urlsafe_b64encode(chart_yaml.encode()).decode()

    def get_value_yaml_contents(self):
        value_content = self.helm_chart._get_values_content_for_alias(
            self.blacklodge_model.name, self.pipeline_alias
        )
        value_yaml = yaml.dump(value_content)
        return base64.urlsafe_b64encode(value_yaml.encode()).decode()


@define
class Blacklodge_Namespace_Deployer_Data(Stratos_Deployer_Data_Interface):
    stratos_application_values: Stratos_Application_Values = field()
    aws_constants: AWS_Accounts_For_Blacklodge = field()
    splunk_constants: Splunk_Constants = field()
    blacklodge_model: Blacklodge_Model = field()
    blacklodge_user: Blacklodge_User = field()
    helm_chart: Helm_Repo_Deployer = field(init=False)

    def __attrs_post_init__(self):
        helm_chart_type = Blacklodge_Helm_Chart_Type.NAMESPACE
        self.helm_chart = Helm_Repo_Deployer(
            helm_chart_type=helm_chart_type,
            stratos_application_values=self.stratos_application_values,
            aws_constants=self.aws_constants,
            splunk_constants=self.splunk_constants,
        )

    def get_stratos_application_name(self) -> str:
        return f"{self.blacklodge_user.get_teamname()}-ns"

    def get_stratos_namespace_name(
        self,
    ):
        return self.blacklodge_user.get_namespace()

    def get_stratos_project_identifier(self) -> str:
        return self.blacklodge_user.get_teamname()

    def get_chart_yaml_contents(self):
        chart_content = self.helm_chart._get_chart_content()
        chart_yaml = yaml.dump(chart_content)
        return base64.urlsafe_b64encode(chart_yaml.encode()).decode()

    def get_value_yaml_contents(self):
        return None


class Stratos_Api_V1_Container_Deployer(Container_Deployer):
    def __init__(
        self,
        container_deploy_data_for_stratos_api: Container_Deploy_Data_For_Stratos_Api_V1,
        stratos_api_caller: Stratos_Api_Caller,
        stratos_endpoint: str = "containerdeploy",
    ) -> None:
        super().__init__()
        self.stratos_endpoint = stratos_endpoint
        self.data = container_deploy_data_for_stratos_api
        self.stratos_api_caller = stratos_api_caller

    def create_stratos_application(self):
        pass

    def deploy_container_image(self) -> Stratos_Response_Wrapper:
        util = Stratos_Api_V1_Util(self.stratos_api_caller)
        # create stratos application
        stratos_application_metadata = Stratos_AppOwnersMetadata_V1(
            repository=self.data.get_stratos_repository(),
            repository_url=self.data.get_stratos_repository_url(),
            application_contact=self.data.get_stratos_application_contact(),
            application_name=self.data.get_stratos_application_name(),
        )
        stratos_application_result = util.create_stratos_application(
            stratos_application_metadata
        )

        if is_ok(stratos_application_result):
            # create stratos project
            project_metadata = Stratos_ProjectMetadata_V1(
                environment_name=self.data.get_stratos_environment(),
                application_name=self.data.get_stratos_application_name(),
                project_identifier=self.data.get_stratos_project_identifier(),
            )
            argocd_proeject_result = util.create_argocd_project_using_stratos_sdk(
                project_metadata
            )
            if is_ok(argocd_proeject_result):
                if argocd_proeject_result.ok_value:
                    # create namepace for team
                    namespace_metadata = Stratos_NamespaceMetadata_V1(
                        environment_name=self.data.get_stratos_environment(),
                        application_name=self.data.get_stratos_application_name(),
                        namespace_identifier=self.data.get_stratos_namespace_name(),
                        project_identifier=self.data.get_stratos_project_identifier(),
                    )
                    print("NAMESPACE ")
                    print(namespace_metadata)
                    util.create_k8s_namespace_using_stratos_sdk(namespace_metadata)
                    print("NAMESPACE\n")

                    # call ther stratos api to commit the helm chart and values
                    helm_data = Stratos_ContainerHelDeployRequest_V1(
                        base64_chart_yaml_contents=self.data.get_chart_yaml_contents(),
                        base64_values_yaml_contents=self.data.get_value_yaml_contents(),
                        environment_name=self.data.get_stratos_environment(),
                        application_name=self.data.get_stratos_application_name(),
                        namespace_identifier=self.data.get_stratos_namespace_name(),
                        project_identifier=self.data.get_stratos_project_identifier(),
                    )
                    print(helm_data)
                    util.deploy_helm_chart_and_values(helm_data)

                    app_sync_request = Stratos_AppSyncArgoRequest_V1(
                        environment_name=self.data.get_stratos_environment(),
                        application_name=self.data.get_stratos_application_name(),
                        project_identifier=self.data.get_stratos_project_identifier(),
                    )
                    util.sync_argocd_application(app_sync_request)

            elif is_err(argocd_proeject_result):
                print(argocd_proeject_result.err_value)
            else:
                print("UNknown Project Result")

        elif is_err(stratos_application_result):
            print("No Stratos Application. " + stratos_application_result.err_value)
        else:
            print("No Stratos Application. " + stratos_application_result.err_value)


@define
class Stratos_Api_V1_Blacklodge_Application_Deployer:
    stratos_application_values: Stratos_Application_Values = field()
    aws_constants: AWS_Accounts_For_Blacklodge = field()
    splunk_constants: Splunk_Constants = field()
    blacklodge_model: Blacklodge_Model = field()
    blacklodge_user: Blacklodge_User = field()
    stratos_api_caller: Stratos_Api_Caller = field()

    def create_k8s_namespace(
        self, deployer_data: Stratos_Deployer_Data_Interface, util: Stratos_Api_V1_Util
    ):
        print("handling k8s namespce....")
        namespace_metadata = Stratos_NamespaceMetadata_V1(
            environment_name=deployer_data.get_stratos_environment(),
            application_name=deployer_data.get_stratos_application_name(),
            namespace_identifier=deployer_data.get_stratos_namespace_name(),
            project_identifier=deployer_data.get_stratos_project_identifier(),
        )
        util.create_k8s_namespace_using_stratos_sdk(namespace_metadata)

    def create_project(
        self, deployer_data: Stratos_Deployer_Data_Interface, util: Stratos_Api_V1_Util
    ):
        print("handling argocd project....")
        project_metadata = Stratos_ProjectMetadata_V1(
            environment_name=deployer_data.get_stratos_environment(),
            application_name=deployer_data.get_stratos_application_name(),
            project_identifier=deployer_data.get_stratos_project_identifier(),
        )
        argocd_proeject_result = util.create_argocd_project_using_stratos_sdk(
            project_metadata
        )
        return argocd_proeject_result

    def deploy_application(
        self, deployer_data: Stratos_Deployer_Data_Interface, util: Stratos_Api_V1_Util
    ):
        self.create_k8s_namespace(deployer_data, util)
        argocd_proeject_result = self.create_project(deployer_data, util)
        if is_ok(argocd_proeject_result):
            if argocd_proeject_result.ok_value:
                # now create a stratos appowners metadata object
                print("handling s5s application....")
                stratos_application_metadata = (
                    Stratos_AppOwnersMetadata_V1.get_data_using_blacklodge_model(
                        blacklodge_model=self.blacklodge_model,
                        application_name=deployer_data.get_stratos_application_name(),
                    )
                )
                stratos_application_result = util.create_stratos_application(
                    stratos_application_metadata
                )
                if is_ok(stratos_application_result):
                    print("handling helm chart and values....")
                    helm_data = Stratos_ContainerHelDeployRequest_V1(
                        base64_chart_yaml_contents=deployer_data.get_chart_yaml_contents(),
                        base64_values_yaml_contents=deployer_data.get_value_yaml_contents(),
                        environment_name=deployer_data.get_stratos_environment(),
                        application_name=deployer_data.get_stratos_application_name(),
                        namespace_identifier=deployer_data.get_stratos_namespace_name(),
                        project_identifier=deployer_data.get_stratos_project_identifier(),
                    )
                    if deployer_data.get_value_yaml_contents():
                        deploy_result = util.deploy_helm_chart_and_values(helm_data)
                    else:
                        deploy_result = util.deploy_helm_chart(helm_data)

                    if is_ok(deploy_result):
                        helm_deploy_success = deploy_result.ok_value
                        if helm_deploy_success:
                            print(f"handling argocd app sync...")
                            app_sync_request = Stratos_AppSyncArgoRequest_V1(
                                environment_name=deployer_data.get_stratos_environment(),
                                application_name=deployer_data.get_stratos_application_name(),
                                project_identifier=deployer_data.get_stratos_project_identifier(),
                            )
                            util.sync_argocd_application(app_sync_request)
                        else:
                            print("Stratos call to update helm chart/vales failed")
                    elif is_err(deploy_result):
                        print(
                            "Stratos call to update helm chart/vales failed with "
                            + deploy_result.err_value
                        )
                    else:
                        print(
                            "Stratos call to update helm chart/vales failed with unknown error"
                        )
                elif is_err(stratos_application_result):
                    print(stratos_application_result.err_value)
                else:
                    print(
                        f"Unknown Error While Creating Stratos Application {deployer_data.get_stratos_application_name()}"
                    )
        elif is_err(argocd_proeject_result):
            print(argocd_proeject_result.err_value)
        else:
            print(
                f"Unknown Error While Creating Stratos Project {deployer_data.get_stratos_project_identifier()}"
            )

    def deploy_pipeline(self):
        # self.deploy_namespace()
        util = Stratos_Api_V1_Util(self.stratos_api_caller)

        deployer_data = Blacklodge_Pipeline_Deployer_Data(
            stratos_application_values=self.stratos_application_values,
            aws_constants=self.aws_constants,
            splunk_constants=self.splunk_constants,
            blacklodge_model=self.blacklodge_model,
            blacklodge_user=self.blacklodge_user,
        )
        print(
            f"Deploying ArgoCD Application for Pipeline {deployer_data.get_stratos_application_name()}..."
        )
        self.deploy_application(deployer_data, util)

    def deploy_alias(self):
        # self.deploy_namespace()
        util = Stratos_Api_V1_Util(self.stratos_api_caller)

        for alias in self.blacklodge_model.aliases:
            deployer_data = Blacklodge_Alias_Deployer_Data(
                stratos_application_values=self.stratos_application_values,
                aws_constants=self.aws_constants,
                splunk_constants=self.splunk_constants,
                blacklodge_model=self.blacklodge_model,
                pipeline_alias=alias,
                blacklodge_user=self.blacklodge_user,
            )
            print(
                f"Deploying ArgoCD Application for Alias {deployer_data.get_stratos_application_name()}..."
            )
            self.deploy_application(deployer_data, util)

    def deploy_namespace(self):
        util = Stratos_Api_V1_Util(self.stratos_api_caller)
        deployer_data = Blacklodge_Namespace_Deployer_Data(
            stratos_application_values=self.stratos_application_values,
            aws_constants=self.aws_constants,
            splunk_constants=self.splunk_constants,
            blacklodge_model=self.blacklodge_model,
            blacklodge_user=self.blacklodge_user,
        )
        print(
            f"Deploying ArgoCD Application for Namespace {deployer_data.get_stratos_application_name()}..."
        )
        self.deploy_application(deployer_data, util)
