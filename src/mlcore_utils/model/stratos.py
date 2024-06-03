from abc import ABC, abstractmethod
import json
from result import is_ok, is_err
import time
import ast
import requests
from typing import Optional, Tuple, Any, Dict
from attrs import define, field

from mlcore_utils.model.common import (
    Http_Method,
    Secret_Getter,
    Blacklodge_Action_Status,
)
from mlcore_utils.model.blacklodge import Blacklodge_Model, Blacklodge_BusinessUnit
from mlcore_utils.model.aws import AWS_Accounts_For_Blacklodge


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
            raise Exception("error getting secret for strator API: " + secret_result.err_value)
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
                        #verify="/etc/ssl/certs/ca-certificates.crt",
                    )
                    return response
                elif http_method == Http_Method.GET:
                    response = requests.get(
                        url=url,
                        json=json_data,
                        headers=self.get_default_stratos_headers(),
                        timeout=timeout,
                        #verify="/etc/ssl/certs/ca-certificates.crt",
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
            # status_response = requests.get(url = f"{self.stratos_url}\\{status_response_url}", headers = self.get_default_stratos_headers())
            status_response = self.call_api(
                http_method=Http_Method.GET,
                endpoint=f"{status_response_url}",
            )
            if status_response.status_code == 200:
                status = status_response.json()["build_status"]
                print("Current status " + status)
                if status.lower() == "completed":
                    conclusion = status_response.json()["conclusion"] if "conclusion" in status_response.json() else "..."
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
class Container_Build_Response(ABC):
    status: Blacklodge_Action_Status = field()
    message: Optional[Dict[str, Any]] = field()
    error: Optional[Dict[str, Any]] = field()


class Container_Builder(object):
    def __init__(self) -> None:
        pass

    @abstractmethod
    def build_container_image(self) -> Container_Build_Response:
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
        res = self.blacklodge_model.runtime_config.blacklodge_container.github_repo.get_commit_sha()
        if is_ok(res):
            return (res.ok_value)
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

    def build_container_image(self) -> Container_Build_Response:
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
                        return Container_Build_Response(
                            status=Blacklodge_Action_Status.SUCCESS,
                            message=call_response[1].json(),
                            error=None,
                        )

                    else:
                        return Container_Build_Response(
                            status=Blacklodge_Action_Status.FAILED,
                            message=None,
                            #error=f"Container Image Built priocess failed. YOu can find details here: <{call_response[1].json()['html_url']}>",
                            error=call_response[1].json(),
                        )

                else:
                    return Container_Build_Response(
                        status=Blacklodge_Action_Status.FAILED,
                        message=None,
                        #error=call_response[1].text,
                        error={"status_code" : call_response[1].status_code, "error" : "request to build image successfulyl submitted. But process failed with error : " + call_response[1].text},
                    )
            else:
                return Container_Build_Response(
                    status=Blacklodge_Action_Status.UNKNOWN,
                    message=None,
                    error={"error" : "Container image built request successfully submitted, but could not get status of the action"},
                )
        else:
            return Container_Build_Response(
                status=Blacklodge_Action_Status.FAILED,
                message=None,
                error={"status_code" : call_response[0].status_code, "error" : "request to build image failed with error: " + call_response[0].text},
            )
