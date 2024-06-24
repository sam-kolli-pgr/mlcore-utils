from __future__ import annotations
from abc import ABC
from logging import Logger
from result import Err, Ok, Result, is_ok, is_err
import time
import requests
from typing import Callable, Optional, Tuple, Any, Dict
from attrs import define, field, asdict

from mlcore_utils.model.common import (
    Http_Method,
    Secret_Getter,
    Blacklodge_Action_Status,
)
from mlcore_utils.model.blacklodge import (
    Blacklodge_Model,
    Blacklodge_User,
)

from mlcore_utils.model.common import Secret_Getter
from mlcore_utils.model.stratos_interface import Stratos_AppOwnersMetadata_V1, Stratos_AppSyncArgoRequest_V1, Stratos_ContainerHelDeployRequest_V1, Stratos_NamespaceMetadata_V1, Stratos_ProjectMetadata_V1


@define
class Requests_Wrapper(object):
    # logger: Logger = field()

    def call_end_point(
        self,
        http_method: Http_Method,
        endpoint: str,
        params=None,
        data=None,
        headers=None,
        json=None,
        timeout: int = 15,
        attempt_count: int = 1,
        retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        # self.logger.info("calling end point " + endpoint)
        if attempt_count > retries:
            raise Exception(
                f"Could not reach endpoint {endpoint} after {retries} attempts"
            )
        try:
            # self.logger.info("calling " + endpoint)
            return requests.request(
                method=http_method.value,
                url=endpoint,
                params=params,
                data=data,
                headers=headers,
                json=json,
                timeout=timeout,
                **kwargs,
            )
        except requests.exceptions.ReadTimeout:
            # self.logger.error(f"retry attempt {attempt_count} for endpoint {endpoint}")
            return self.call_end_point(
                http_method,
                endpoint,
                params,
                data,
                headers,
                json,
                timeout,
                attempt_count + 1,
                **kwargs,
            )
        except Exception as e:
            # self.logger.error("error calling endpoint {endpoint}")
            raise e

    def call_url_till_condition_is_met(
        self,
        status_response_url: str,
        action_to_perform,
        condition_to_meet: Callable[[requests.Response], bool],
    ) -> Result[requests.Response, str]:
        finished = False
        seconds_to_wait = 60
        num_attempt = 0
        while not (finished or num_attempt > 30):
            try:
                # status_response = self.call_api(
                #    http_method=Http_Method.GET,
                #    endpoint=f"{status_response_url}",
                # )
                status_response = action_to_perform()
                if status_response.status_code == 200:
                    condition_is_met = condition_to_meet(status_response)
                    if condition_is_met:
                        finished = True
                        return Ok(status_response)
                    else:
                        time.sleep(seconds_to_wait)
                        num_attempt = num_attempt + 1
                else:
                    time.sleep(seconds_to_wait)
                    num_attempt = num_attempt + 1
            except Exception as e:
                raise e
                # return Err(f"Cound not get status from {status_response_url}. Error {str(e)}")


class ArgoCD_Api_Caller(object):
    def __init__(
        self,
        secret_getter: Secret_Getter,
        requests_wrapper: Requests_Wrapper,
    ):
        self.secret_getter = secret_getter
        self.version = 1
        self.argocd_url = f"https://argocd.mgmt.stratos.prci.com/api/v{self.version}"
        self.requests_wrapper = requests_wrapper

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
        data=None,
        timeout: int = 15,
        current_attempt_count: int = 1,
        max_number_of_attempts: int = 3,
        params=None,
        **kwargs,
    ) -> requests.Response:
        try:
            url = f"{self.argocd_url}/{endpoint}"
            response = self.requests_wrapper.call_end_point(
                http_method=http_method,
                endpoint=url,
                params=params,
                data=data,
                headers=self.get_default_headers(),
                json=json_data,
                timeout=timeout,
                attempt_count=current_attempt_count,
                retries=max_number_of_attempts,
                **kwargs,
            )
            return response
        except Exception as e:
            raise e

    def call_status_url_and_await(
        self, status_response_url
    ) -> Result[requests.Response, str]:
        condition_to_meet = lambda status_response: status_response.json()["status"][
            "health"
        ]["status"]

        def _a():
            return self.call_api(
                http_method=Http_Method.GET, endpoint=status_response_url
            )

        return self.requests_wrapper.call_url_till_condition_is_met(
            status_response_url, _a, condition_to_meet
        )


class Stratos_Api_Caller(object):
    def __init__(
        self,
        secret_getter: Secret_Getter,
        requests_wrapper: Requests_Wrapper,
    ) -> None:
        self.secret_getter = secret_getter
        self.stratos_url = f"https://jetstreamapi.apps.stratos.prci.com/api/v1/stratos"
        self.requests_wrapper = requests_wrapper

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
        data=None,
        timeout: int = 15,
        current_attempt_count: int = 1,
        max_number_of_attempts: int = 3,
        params=None,
        **kwargs,
    ) -> requests.Response:
        try:
            url = f"{self.stratos_url}/{endpoint}"
            response = self.requests_wrapper.call_end_point(
                http_method=http_method,
                endpoint=url,
                params=params,
                data=data,
                headers=self.get_default_stratos_headers(),
                json=json_data,
                timeout=timeout,
                attempt_count=current_attempt_count,
                retries=max_number_of_attempts,
                **kwargs,
            )
            return response
        except Exception as e:
            raise e

    def call_status_url_and_await(
        self, status_response_url
    ) -> Result[requests.Response, str]:
        condition_to_meet = (
            lambda status_response: status_response.json()["build_status"]
            == "completed"
        )

        def _a():
            r = self.call_api(http_method=Http_Method.GET, endpoint=status_response_url)
            print(r.status_code)
            print(r.text)
            return r

        response = self.requests_wrapper.call_url_till_condition_is_met(
            status_response_url, _a, condition_to_meet
        )
        if is_ok(response):
            print(response.ok_value.status_code)
        elif is_err(response):
            print(response.err_value)
        else:
            print("....")
        return response

    def call_api_old(
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

    def call_status_url_and_await_old(self, status_response_url):
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
                    print(
                        "app not yet available in argocd. will check again in 60 seconds..."
                    )
                    time.sleep(60)
                    return self.sync_argocd_application(
                        app_sync_request, stratos_call_success, attempt + 1
                    )
                else:
                    print(response.status_code)
                    print(response.text)
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
